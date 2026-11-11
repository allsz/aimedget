"""
Valida um tema do Aimedget e explica, em português, o que está errado e como corrigir.

    python tools/validate_theme.py <pasta-do-tema> [--container keylock|mixer|music|timer] [--json]

- <pasta-do-tema> tem um theme.json e as imagens ao lado dele. Para um pacote com vários destinos, aponte
  a pasta que contém as subpastas keylock/, mixer/, music/ e/ou timer/.
- O container é deduzido pelo nome das pastas (themes/keylock/meu-tema); se não der, use --container.
- Código de saída: 0 = tudo certo; 1 = há problemas (valores ignorados ou erro fatal); 2 = uso incorreto.
- --json imprime o relatório em JSON (útil para uma IA ler e se autocorrigir).

A validação usa o mesmo código que o flyout usa para ler o tema, então "passou aqui" = "vale no app".
"""

import argparse
import json
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.theme_validation import CONTAINER_NAMES, CONTAINERS, ThemeReport, validate_path  # noqa: E402

NOMES = CONTAINER_NAMES


def print_report(report: ThemeReport) -> None:
    title = report.name or os.path.basename(report.folder)
    print(f"\n=== {NOMES.get(report.container, report.container)} — {title} ===")
    print(f"Pasta: {report.folder}")
    for message in report.errors:
        print(f"  [ERRO] {message}")
    if report.errors:
        print("  O tema NÃO pode ser usado até corrigir o erro acima.")
        return
    if report.applied:
        extra = f" ({report.sticker_count} figurinha(s))" if report.sticker_count else ""
        print(f"  Aplicado: {', '.join(report.applied)}{extra}")
    else:
        print("  Aplicado: nada (o tema ficaria igual ao visual padrão)")
    for message in report.issues:
        print(f"  [IGNORADO] {message}")
    print("  Resultado: tudo certo." if report.ok else
          f"  Resultado: o tema abre, mas {len(report.issues)} item(ns) acima foram ignorados.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Valida um tema do Aimedget.")
    parser.add_argument("folder", help="pasta do tema (ou do pacote com keylock/, mixer/, music/, timer/)")
    parser.add_argument("--container", choices=CONTAINERS, help="destino do tema (se não der para deduzir)")
    parser.add_argument("--json", action="store_true", help="imprime o relatório em JSON")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):   # acentos corretos também quando a saída vai para um pipe/arquivo
        stream.reconfigure(encoding="utf-8", errors="replace")
    logging.disable(logging.WARNING)           # o relatório já mostra cada aviso; sem repetir no log

    app =QApplication.instance() or QApplication([])  # noqa: F841  (imagens usam QPixmap)
    try:
        reports = validate_path(args.folder, args.container)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print_report(report)
        print()
    return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
