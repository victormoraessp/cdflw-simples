"""Gera um export sintetico no formato da lista do CadFlow (cabecalhos como no SharePoint).

Uso: python exemplos/gerar_export.py [destino.xlsx]
"""

from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook

CABECALHO = [
    "Title", "codigo_regra", "codgo_regra_comp", "Criado", "ID", "tipo_regra", "criticidade",
    "descricao_bloco", "nome_regra", "descricao_regra", "objetivo", "criterio_aplicacao", "logica_execucao",
    "resultado", "exemplo", "acao_dado_valido", "acao_dado_invalido", "tipo_pessoa_afetada", "observacao",
    "metrica_monitoramento", "status", "is_editing", "is_backlog", "is_legacy", "codigos_regra_geral",
    "sequencia_desenvolvimento", "Tipo de Item", "Caminho",
]

LINHAS = [
    ["RN1", "ICT.RN.1", "", "7/7/2026 10:00", 601, "Negócio", "Alta", "Dados de Contato",
     "Consistência do telefone de contato de uma pessoa física",
     "Verifica o telefone de contato de pessoa física, buscando qualificar os dados.",
     "Consistir o telefone de contato de pessoa física.",
     "Executar em todo o cadastro de pessoa física.",
     "O conjunto de regras verifica o conteúdo dos campos de DDD, número e tipo do telefone de contato buscando consistir a informação.",
     "Registros verificados e mantidos com dados consistentes.", "", "Manter a informação consistente.",
     "Para registros inconsistentes, executar as regras previstas, conforme o campo.", "PF", "n/a", "", "Aprovada",
     "FALSO", "FALSO", "FALSO", "", "1", "Item", "teams/x/Lists/regras_exemplo"],
    ["RN1", "ICT.RV.1", "ICT.RN1.RV1", "7/8/2026 11:00", 602, "Validação", "Baixa", "Dados de Contato",
     "Validação do DDD do telefone de contato",
     "Valida se o DDD do telefone de contato está dentro dos domínios permitidos.",
     "Validar o DDD do telefone de contato de pessoa física.",
     "Executar em todos os registros que possuam conteúdo no campo DDD do telefone de contato.",
     "SE CMPO_DDD_TEL não pertence a (TDDD - XDOM001) ENTÃO segregar como inconsistente",
     "nan", "DDD 11 válido; DDD 00 inválido.", "Manter dado",
     "Segregar como inconsistente: \"DDD do telefone invalido\". Executar regra ICT.RL.1.", "PF", "", "", "Aprovada",
     "FALSO", "FALSO", "VERDADEIRO", "", "2", "Item", "teams/x/Lists/regras_exemplo"],
    ["RN1", "ICT.RL.1", "ICT.RN1.RL1", "7/9/2026 09:30", 603, "Limpeza", "Alta", "Dados de Contato",
     "Saneamento do DDD do telefone de contato",
     "Apaga o conteúdo do campo DDD do telefone de contato por não pertencer aos domínios permitidos.",
     "Apagar o conteúdo do campo DDD do telefone de contato.",
     "Executar em todos os registros que foram segregados como inconsistentes pela regra ICT.RV.1.",
     "A regra apaga o conteúdo do campo CMPO_DDD_TEL nos registros que foram segregados como inconsistentes.",
     "Sucesso: os campos inconsistentes são apagados. Falha: registro não apagado.", "", "", "", "PF", "", "",
     "Em construção", "VERDADEIRO", "FALSO", "FALSO", "", "3", "Item", "teams/x/Lists/regras_exemplo"],
]


def gerar(destino: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "export"
    ws.append(CABECALHO)
    for l in LINHAS:
        ws.append(l)
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino


if __name__ == "__main__":
    alvo = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "base" / "Extracao CadFlow exemplo.xlsx"
    print(gerar(alvo))
