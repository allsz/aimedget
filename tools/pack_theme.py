"""
Valida um tema e gera o arquivo .aimskin (um zip) pronto para importar ou compartilhar, em um comando.

    python tools/pack_theme.py <pasta> [-o saida.aimskin] [--container keylock|mixer|music|timer] [--allow-issues]

- <pasta> é a pasta do tema (com theme.json e as imagens) ou a pasta que contém keylock/, mixer/, music/ e/ou timer/.
- O destino é deduzido pelo nome das pastas (themes/keylock/meu-tema); se não der, use --container.
- Se a validação achar erro, nada é gerado. Itens ignorados (valores inválidos) também barram, para o tema sair
  como o designer pensou; use --allow-issues só se quiser empacotar mesmo assim.
- Só entram theme.json e imagens (png/jpg/jpeg/webp/svg). Arquivos de outros tipos, ocultos ou grandes demais
  ficam de fora e são listados. Arquivos de imagem que o theme.json não usa entram, mas geram um aviso.
- Depois de gerar, o pacote é reaberto com o mesmo código da importação do app, para conferir que é importável.
- Código de saída: 0 pacote gerado · 1 há problemas (nada gerado) · 2 uso incorreto.
"""

import argparse
import json
import logging
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, ROOT)
sys.path.insert(0, TOOLS)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.theme_package import (  # noqa: E402
    ALLOWED_EXTENSIONS, PACKAGE_EXT, PackageError, analyze_package, collect_folder_files, pack_folders, slugify,
)
from app.core.theme_validation import CONTAINERS, ThemeReport, validate_path  # noqa: E402
from validate_theme import NOMES, print_report  # noqa: E402


def referenced_files(folder: str) -> set[str]:
    """Nomes de arquivo citados em "image" no theme.json (fundo e figurinhas), em minúsculas e com '/'."""
    found: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "image" and isinstance(value, str):
                    found.add(value.replace("\\", "/").lower())
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    try:
        with open(os.path.join(folder, "theme.json"), "r", encoding="utf-8") as f:
            walk(json.load(f))
    except (OSError, ValueError):
        pass
    return found


def left_out_files(folder: str) -> list[str]:
    """Arquivos da pasta que NÃO entram no pacote (tipo não permitido, ocultos ou grandes demais)."""
    included = {rel for _full, rel in collect_folder_files(folder)}
    out = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in sorted(names):
            rel = os.path.relpath(os.path.join(root, fname), folder).replace(os.sep, "/")
            if rel not in included:
                out.append(rel)
    return out


def unused_files(folder: str) -> list[str]:
    used = referenced_files(folder)
    return [rel for _full, rel in collect_folder_files(folder)
            if rel != "theme.json" and not rel.lower().endswith(".json") and rel.lower() not in used]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Valida um tema e gera o .aimskin.")
    parser.add_argument("folder", help="pasta do tema (ou do pacote com keylock/, mixer/, music/, timer/)")
    parser.add_argument("-o", "--output", help=f"arquivo de saída (padrão: <nome-do-tema>{PACKAGE_EXT} ao lado da pasta)")
    parser.add_argument("--container", choices=CONTAINERS, help="destino do tema (se não der para deduzir)")
    parser.add_argument("--allow-issues", action="store_true", help="empacota mesmo com itens ignorados")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    logging.disable(logging.WARNING)
    app = QApplication.instance() or QApplication([])  # noqa: F841  (imagens usam QPixmap)

    try:
        reports: list[ThemeReport] = validate_path(args.folder, args.container)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    for report in reports:
        print_report(report)
        for rel in unused_files(report.folder):
            print(f"  [AVISO] {rel}: nenhum campo 'image' do theme.json usa este arquivo (não precisa ir no pacote)")
        for rel in left_out_files(report.folder):
            print(f"  [FORA DO PACOTE] {rel}: tipo não permitido, oculto ou grande demais "
                  f"(só {', '.join(e.lstrip('.') for e in ALLOWED_EXTENSIONS)})")

    if any(r.errors for r in reports):
        print("\nNada foi gerado: corrija os [ERRO] acima.")
        return 1
    if any(r.issues for r in reports) and not args.allow_issues:
        print("\nNada foi gerado: há itens ignorados. Corrija-os, ou use --allow-issues para empacotar assim mesmo.")
        return 1

    name = next((r.name for r in reports if r.name), "") or os.path.basename(os.path.normpath(args.folder))
    output = args.output or os.path.join(os.path.dirname(os.path.abspath(args.folder)), slugify(name) + PACKAGE_EXT)
    if not output.lower().endswith(PACKAGE_EXT):
        output += PACKAGE_EXT
    try:
        count = pack_folders([(r.container, r.folder) for r in reports], output, name=name)
        check = analyze_package(output)
    except (PackageError, OSError) as exc:
        print(f"\nNão foi possível gerar o pacote: {exc}", file=sys.stderr)
        return 1

    try:
        print(f"\nPacote gerado: {output}")
        print(f"  {count} arquivo(s), {os.path.getsize(output) // 1024} KB | tema: {check.name!r} (id {check.theme_id})")
        for target in check.targets:
            state = "pronto para instalar" if target.report.ok else f"{len(target.report.issues)} item(ns) ignorado(s)"
            print(f"  - {NOMES.get(target.container, target.container)}: {state}")
        for rel, why in check.ignored_files:
            print(f"  [IGNORADO NA IMPORTAÇÃO] {rel}: {why}")
        if not all(t.installable for t in check.targets):
            print("Atenção: o pacote gerado não passou na verificação da importação.", file=sys.stderr)
            return 1
    finally:
        check.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
