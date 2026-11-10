"""
Pacote de tema (.aimskin = zip): análise segura, instalação e exportação. Só dados, nunca executa nada.

Formato do pacote (o designer escolhe um):
    keylock/theme.json + imagens        (tema do Caps/Num Lock)
    mixer/theme.json   + imagens        (tema do Volume e mixer)      <- as duas pastas juntas = pacote multi-alvo
    theme.json (com "container": "keylock" ou "mixer") + imagens    <- tema de um flyout só, sem subpasta
Uma única pasta de embrulho em volta de tudo (Lavanda/keylock/...) também é aceita.

Fluxo: `analyze_package` extrai para uma pasta temporária com TODAS as defesas e valida cada alvo com o mesmo
código do flyout (theme_validation); o chamador mostra o relatório; `install_package` copia para
themes/<container>/<id>/ só o que o usuário confirmou. Nada é instalado antes disso.

Defesas (qualquer uma recusa o pacote inteiro): caminho absoluto, `..`, letra de unidade, `:` (fluxo alternativo do
NTFS), nomes reservados do Windows, link simbólico, arquivo criptografado, nomes repetidos, arquivos demais, tamanho
total demais (conferido na extração de verdade, não só no cabeçalho do zip). Arquivos fora das extensões permitidas
ou fora das pastas dos flyouts NÃO são extraídos e aparecem como "ignorados" com o motivo.
"""

import json
import os
import re
import shutil
import stat
import struct
import tempfile
import unicodedata
import uuid
import zipfile
import zlib
from dataclasses import dataclass, field

from app.core.theme_art import MAX_FILE_BYTES, MAX_SVG_BYTES
from app.core.theme_loader import CUSTOM_ID, DEFAULT_ID, MAX_NAME_LEN
from app.core.theme_validation import CONTAINERS, ThemeReport, validate_theme_folder

PACKAGE_EXT = ".aimskin"
ALLOWED_EXTENSIONS = (".json", ".png", ".jpg", ".jpeg", ".webp", ".svg")
MAX_PACKAGE_BYTES = 40 * 1024 * 1024      # o próprio .aimskin
MAX_FILES = 120                           # entradas no zip (pastas não contam)
MAX_TOTAL_BYTES = 40 * 1024 * 1024        # tudo descompactado
MAX_JSON_BYTES = 256 * 1024
MAX_PATH_LEN = 120
MAX_PART_LEN = 60
MAX_DEPTH = 4                             # níveis de pasta dentro do tema

_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_MODE_REPLACE, _MODE_COPY = "replace", "copy"
REPLACE, COPY = _MODE_REPLACE, _MODE_COPY


class PackageError(Exception):
    """Pacote recusado (mensagem em pt-BR, pronta para mostrar ao usuário)."""


# --- Caminhos e limites ----------------------------------------------------------------------

def _clean_member_path(name: str) -> str:
    """Caminho normalizado ('/' como separador) ou PackageError. Recusa tudo que possa escapar da pasta."""
    raw = name.replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise PackageError(f"caminho absoluto não é permitido: {name!r}")
    if len(raw) > MAX_PATH_LEN:
        raise PackageError(f"nome de arquivo comprido demais: {name[:40]!r}...")
    parts = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise PackageError(f"o pacote tenta sair da própria pasta (..): {name!r}")
        if any(ord(c) < 32 for c in part) or ":" in part or any(c in part for c in '<>"|?*'):
            raise PackageError(f"nome de arquivo com caractere proibido: {name!r}")
        if part.endswith((".", " ")) or len(part) > MAX_PART_LEN:
            raise PackageError(f"nome de arquivo inválido: {name!r}")
        if part.split(".")[0].lower() in _RESERVED:
            raise PackageError(f"nome reservado do Windows: {name!r}")
        parts.append(part)
    if not parts:
        raise PackageError(f"nome de arquivo vazio: {name!r}")
    return "/".join(parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return bool(mode) and stat.S_ISLNK(mode)


def _size_cap(ext: str) -> int:
    return MAX_JSON_BYTES if ext == ".json" else MAX_SVG_BYTES if ext == ".svg" else MAX_FILE_BYTES


def slugify(text: str) -> str:
    """Id de pasta seguro a partir de um nome: minúsculas, sem acento, só a-z 0-9 e '-'."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:MAX_NAME_LEN]
    return slug.strip("-") or "tema"


# --- Relatório -------------------------------------------------------------------------------

@dataclass
class TargetReport:
    container: str
    folder: str                    # pasta (temporária) com os arquivos a instalar
    report: ThemeReport            # o que vale / o que será ignorado
    exists: bool = False           # já há um tema com este id instalado neste flyout

    @property
    def name(self) -> str:
        return self.report.name

    @property
    def installable(self) -> bool:
        return self.report.usable


@dataclass
class PackageReport:
    path: str
    name: str
    theme_id: str
    targets: list[TargetReport] = field(default_factory=list)
    ignored_files: list[tuple[str, str]] = field(default_factory=list)   # (arquivo, motivo)
    workdir: tempfile.TemporaryDirectory | None = None

    @property
    def installable_targets(self) -> list[TargetReport]:
        return [t for t in self.targets if t.installable]

    @property
    def has_collision(self) -> bool:
        return any(t.exists for t in self.installable_targets)

    def close(self):
        if self.workdir is not None:
            self.workdir.cleanup()
            self.workdir = None


@dataclass(frozen=True)
class Installed:
    container: str
    theme_id: str
    folder: str
    replaced: bool


# --- Análise ---------------------------------------------------------------------------------

def themes_dir(container: str) -> str:
    """Pasta de temas do container (a mesma do loader do flyout)."""
    from app.core.config_manager import config_manager
    return os.path.join(config_manager.config_dir, "themes", container)


def _read_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
    """Lista (entrada, caminho limpo) dos ARQUIVOS do zip, já com todas as recusas de segurança."""
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise PackageError(f"o pacote tem arquivos demais ({len(infos)}; máximo {MAX_FILES})")
    members, seen = [], set()
    for info in infos:
        if info.flag_bits & 0x1:
            raise PackageError("o pacote tem arquivos protegidos por senha")
        if _is_symlink(info):
            raise PackageError(f"o pacote contém um atalho/link, que não é permitido: {info.filename!r}")
        clean = _clean_member_path(info.filename)
        key = clean.lower()
        if key in seen:
            raise PackageError(f"o pacote tem o mesmo arquivo duas vezes: {clean!r}")
        seen.add(key)
        members.append((info, clean))
    if sum(i.file_size for i, _ in members) > MAX_TOTAL_BYTES:
        raise PackageError(f"o pacote é grande demais depois de aberto (máximo {MAX_TOTAL_BYTES // (1024 * 1024)} MB)")
    return members


def _strip_wrapper(paths: list[str]) -> str:
    """Prefixo de uma única pasta de embrulho (ex.: 'Lavanda/'), se TODOS os arquivos estiverem nela."""
    firsts = {p.split("/")[0] for p in paths if "/" in p}
    if len(firsts) == 1 and all("/" in p for p in paths):
        only = firsts.pop()
        if only.lower() not in CONTAINERS:
            return only + "/"
    return ""


def _root_container(data: bytes) -> str | None:
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    value = parsed.get("container") if isinstance(parsed, dict) else None
    return value if value in CONTAINERS else None


def _extract(zf, info, dest_path: str, cap: int, budget: list[int]) -> None:
    """Copia UMA entrada contando os bytes de verdade (o tamanho do cabeçalho do zip pode mentir)."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    written = 0
    with zf.open(info) as src, open(dest_path, "wb") as dst:
        while True:
            chunk = src.read(64 * 1024)
            if not chunk:
                break
            written += len(chunk)
            budget[0] += len(chunk)
            if written > cap or budget[0] > MAX_TOTAL_BYTES:
                raise PackageError("o pacote declara tamanhos menores do que realmente tem (recusado por segurança)")
            dst.write(chunk)


def analyze_package(path: str) -> PackageReport:
    """
    Abre o .aimskin, extrai só o permitido para uma pasta temporária e valida cada alvo.
    Levanta PackageError se o pacote for recusado. Quem recebe o relatório deve chamar `close()`.
    """
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise PackageError(f"não foi possível abrir o arquivo ({exc})") from exc
    if size > MAX_PACKAGE_BYTES:
        raise PackageError(f"o arquivo é grande demais ({size // (1024 * 1024)} MB; máximo {MAX_PACKAGE_BYTES // (1024 * 1024)} MB)")

    workdir = tempfile.TemporaryDirectory(prefix="aimskin-")
    try:
        return _analyze(path, workdir)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError, struct.error) as exc:
        workdir.cleanup()   # zip corrompido, truncado ou com compressão que não suportamos
        raise PackageError("o pacote está corrompido ou usa um formato de zip não suportado") from exc
    except BaseException:
        workdir.cleanup()
        raise


def _analyze(path: str, workdir: tempfile.TemporaryDirectory) -> PackageReport:
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise PackageError("o arquivo não é um pacote .aimskin válido (zip corrompido ou de outro tipo)") from exc

    with zf:
        members = _read_members(zf)
        prefix = _strip_wrapper([c for _, c in members])
        members = [(i, c[len(prefix):]) for i, c in members]

        root_theme = next(((i, c) for i, c in members if c.lower() == "theme.json"), None)
        has_folders = any(c.split("/")[0].lower() in CONTAINERS and "/" in c for _, c in members)
        ignored: list[tuple[str, str]] = []

        # Decide o destino (container, caminho relativo) de cada arquivo
        routing: dict[str, str] = {}   # caminho no zip -> container
        if root_theme is not None and has_folders:
            raise PackageError("o pacote mistura theme.json solto com as pastas keylock/ e mixer/; use só um dos formatos")
        if root_theme is not None:
            with zf.open(root_theme[0]) as f:
                container = _root_container(f.read(MAX_JSON_BYTES + 1))
            if container is None:
                raise PackageError('o theme.json solto precisa dizer o flyout: "container": "keylock" ou "mixer" '
                                   "(ou coloque os arquivos dentro de uma pasta keylock/ ou mixer/)")
            for _i, c in members:
                routing[c] = container
        else:
            for _i, c in members:
                top = c.split("/")[0].lower()
                if "/" in c and top in CONTAINERS:
                    routing[c] = top
        if not routing:
            raise PackageError("não achei nenhum tema no pacote: faltam as pastas keylock/ ou mixer/ com um theme.json")

        budget = [0]
        staged: dict[str, str] = {}   # container -> pasta temporária
        for info, clean in members:
            container = routing.get(clean)
            if container is None:
                ignored.append((clean, "fora das pastas keylock/ e mixer/"))
                continue
            rel = clean if root_theme is not None else clean.split("/", 1)[1]
            ext = os.path.splitext(rel)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                ignored.append((clean, f"tipo de arquivo não permitido ({ext or 'sem extensão'}); só "
                                       f"{', '.join(e.lstrip('.') for e in ALLOWED_EXTENSIONS)}"))
                continue
            if rel.count("/") > MAX_DEPTH:
                ignored.append((clean, f"pasta funda demais (máximo {MAX_DEPTH} níveis)"))
                continue
            cap = _size_cap(ext)
            if info.file_size > cap:
                ignored.append((clean, f"arquivo grande demais ({info.file_size // 1024} KB; máximo {cap // 1024} KB)"))
                continue
            folder = staged.setdefault(container, os.path.join(workdir.name, container))
            _extract(zf, info, os.path.join(folder, *rel.split("/")), cap, budget)

    targets: list[TargetReport] = []
    for container in CONTAINERS:
        folder = staged.get(container)
        if folder is None:
            continue
        targets.append(TargetReport(container, folder, validate_theme_folder(folder, container)))

    pack_name = next((t.name for t in targets if t.name), "") or os.path.splitext(os.path.basename(path))[0]
    pack_name = pack_name[:MAX_NAME_LEN]
    theme_id = _free_base_id(slugify(pack_name))
    for t in targets:
        t.exists = os.path.isdir(os.path.join(themes_dir(t.container), theme_id))
    return PackageReport(path=path, name=pack_name, theme_id=theme_id, targets=targets,
                         ignored_files=ignored, workdir=workdir)


def _free_base_id(slug: str) -> str:
    """O id não pode ser um dos reservados (padrão / personalizado)."""
    return f"{slug}-tema" if slug in (DEFAULT_ID, CUSTOM_ID) else slug


# --- Instalação ------------------------------------------------------------------------------

def _unique_copy_id(base: str, containers: list[str]) -> tuple[str, int]:
    n = 2
    while any(os.path.exists(os.path.join(themes_dir(c), f"{base}-{n}")) for c in containers):
        n += 1
    return f"{base}-{n}", n


def _rename_in_json(folder: str, name: str) -> None:
    path = os.path.join(folder, "theme.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["name"] = name[:MAX_NAME_LEN]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def install_package(report: PackageReport, containers: list[str], mode: str = REPLACE) -> list[Installed]:
    """
    Instala os alvos escolhidos em themes/<container>/<id>/. `mode`: REPLACE (padrão: troca o tema de mesmo id)
    ou COPY (instala com um id novo, ex.: lavanda-2, e o nome ganha " (2)"). Cada pasta é montada ao lado e
    só então trocada de lugar, então uma falha no meio não deixa um tema pela metade.
    """
    if mode not in (REPLACE, COPY):
        raise ValueError(f"modo desconhecido: {mode!r}")
    chosen = [t for t in report.installable_targets if t.container in containers]
    if not chosen:
        raise PackageError("nenhum tema selecionado para instalar")

    theme_id, copy_n = report.theme_id, 0
    if mode == COPY:
        theme_id, copy_n = _unique_copy_id(report.theme_id, [t.container for t in chosen])

    installed: list[Installed] = []
    for target in chosen:
        base = themes_dir(target.container)
        os.makedirs(base, exist_ok=True)
        dest = os.path.join(base, theme_id)
        token = uuid.uuid4().hex[:8]
        staging = os.path.join(base, f".novo-{token}")    # começa com '.': o loader ignora
        backup = os.path.join(base, f".antigo-{token}")
        try:
            shutil.copytree(target.folder, staging)
            if copy_n:
                _rename_in_json(staging, f"{target.name or report.name} ({copy_n})")
            replaced = os.path.isdir(dest)
            if replaced:
                os.rename(dest, backup)
            try:
                os.rename(staging, dest)
            except OSError:
                if replaced:
                    os.rename(backup, dest)   # volta o que havia
                raise
            if replaced:
                shutil.rmtree(backup, ignore_errors=True)
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise PackageError(f"não foi possível instalar em {base} ({exc})") from exc
        installed.append(Installed(target.container, theme_id, dest, replaced))
    return installed


# --- Exportação ------------------------------------------------------------------------------

def _theme_json_with_name(full: str, name: str) -> bytes | None:
    """O theme.json com um "name" garantido (o id do tema importado vem dele). None = copiar o arquivo como está."""
    try:
        with open(full, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or (isinstance(data.get("name"), str) and data["name"].strip()):
        return None
    data = {"name": name[:MAX_NAME_LEN], **data}
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def collect_folder_files(folder: str, top_level_only: bool = False) -> list[tuple[str, str]]:
    """(caminho completo, caminho relativo com '/') dos arquivos de tema permitidos de uma pasta, sem ocultos."""
    files: list[tuple[str, str]] = []
    for root, dirs, names in os.walk(folder):
        if top_level_only:
            dirs[:] = []                           # o tema solto da raiz só inclui os arquivos soltos
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in sorted(names):
            if fname.startswith("."):
                continue                           # arquivos ocultos (ex.: .DS_Store) não vão no pacote
            full = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()
            if ext in ALLOWED_EXTENSIONS and os.path.getsize(full) <= _size_cap(ext):
                files.append((full, os.path.relpath(full, folder).replace(os.sep, "/")))
    return files


def _collect_files(container: str, theme_id: str) -> list[tuple[str, str]]:
    """Arquivos de UM tema instalado (themes/<container>/<id>/)."""
    if container not in CONTAINERS:
        raise ValueError(f"container desconhecido: {container!r}")
    if theme_id == DEFAULT_ID:
        raise PackageError("o visual Padrão não pode ser exportado (ele já vem com o app)")
    base = themes_dir(container)
    folder = base if theme_id == CUSTOM_ID else os.path.join(base, theme_id)
    if os.path.basename(theme_id) != theme_id or theme_id.startswith(".") or not os.path.isfile(os.path.join(folder, "theme.json")):
        raise PackageError("não achei a pasta deste tema")
    return collect_folder_files(folder, top_level_only=(theme_id == CUSTOM_ID))


def _write_package(collected: list[tuple[str, list[tuple[str, str]]]], dest_path: str, title: str) -> int:
    """Grava o zip a partir de [(container, [(arquivo, relativo)])]; confere os limites do pacote."""
    all_files = [f for _c, files in collected for f, _rel in files]
    if len(all_files) > MAX_FILES or sum(os.path.getsize(f) for f in all_files) > MAX_TOTAL_BYTES:
        raise PackageError("o tema é grande demais para empacotar (reduza as imagens)")
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for container, files in collected:
            for full, rel in files:
                patched = _theme_json_with_name(full, title) if rel == "theme.json" else None
                if patched is not None:
                    zf.writestr(f"{container}/{rel}", patched)
                else:
                    zf.write(full, f"{container}/{rel}")
    return len(all_files)


def pack_folders(items: list[tuple[str, str]], dest_path: str, name: str | None = None) -> int:
    """
    Empacota pastas de tema AVULSAS (não instaladas): `items` = [(container, pasta)], um por flyout. Cada pasta vai
    para <container>/ dentro do zip. Se um theme.json não tiver "name", leva `name`. Devolve quantos arquivos entraram.
    """
    if not items:
        raise PackageError("nenhuma pasta para empacotar")
    if len({c for c, _ in items}) != len(items):
        raise ValueError("uma pasta por flyout")
    collected = []
    for container, folder in items:
        if container not in CONTAINERS:
            raise ValueError(f"container desconhecido: {container!r}")
        if not os.path.isfile(os.path.join(folder, "theme.json")):
            raise PackageError(f"falta o theme.json em {folder}")
        collected.append((container, collect_folder_files(folder)))
    return _write_package(collected, dest_path, name or os.path.basename(os.path.normpath(items[0][1])))


def export_themes(items: list[tuple[str, str]], dest_path: str, name: str | None = None) -> int:
    """
    Grava UM .aimskin com o tema de cada (container, id) de `items`, no formato <container>/... (um item por flyout).
    Devolve quantos arquivos entraram. O visual Padrão não tem arquivos e não se exporta.
    Se um theme.json não tiver "name", o pacote leva `name` (ou o id do tema): quem importa não depende do
    nome do arquivo .aimskin.
    """
    if not items:
        raise PackageError("nenhum tema para exportar")
    if len({c for c, _ in items}) != len(items):
        raise ValueError("um tema por flyout")
    collected = [(container, _collect_files(container, theme_id)) for container, theme_id in items]
    return _write_package(collected, dest_path, name or items[0][1])


def export_theme(container: str, theme_id: str, dest_path: str, name: str | None = None) -> int:
    """Exporta o tema de UM flyout (atalho de `export_themes`)."""
    return export_themes([(container, theme_id)], dest_path, name)


def has_theme(container: str, theme_id: str) -> bool:
    """Existe uma pasta de tema com este id neste flyout? (para exportar o par Caps + Mixer juntos)"""
    if theme_id in (DEFAULT_ID, CUSTOM_ID) or os.path.basename(theme_id) != theme_id or theme_id.startswith("."):
        return False
    return os.path.isfile(os.path.join(themes_dir(container), theme_id, "theme.json"))
