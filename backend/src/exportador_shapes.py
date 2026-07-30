"""Injeta, no .xlsx já salvo pelo openpyxl, os cards e ícones extraídos do
arquivo-modelo `resultado/Modelo_principal_conciliacao_status.xlsx`.

Contexto (ver docs/HISTORICO_DECISOES.md): os "cards" do modelo não são
células formatadas — são formas do Excel (retângulo de cantos arredondados +
texto) e ícones (imagem PNG/SVG de um banco de ícones do Office), com posição
e tamanho absolutos (EMU). O openpyxl não tem suporte para criar esse tipo de
forma/texto. Por isso os componentes XML e as imagens do modelo foram
extraídos **uma única vez** (nunca em tempo de execução, nunca reabrindo o
modelo) para `src/assets/painel_visual/` — este módulo só troca os 5 valores
de texto do template (nunca a posição, cor, ícone, fonte ou formato) e grava
o resultado como partes novas dentro do .xlsx que o exportador acabou de
salvar. O arquivo-modelo em si nunca é lido nem sobrescrito por esta função.

Nada aqui decide ou altera dado de conciliação — é só a camada de
apresentação, chamada depois que a planilha já foi salva com todos os dados.
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

PASTA_ASSETS = Path(__file__).resolve().parent / "assets" / "painel_visual"
PASTA_MEDIA = PASTA_ASSETS / "media"

# Nomes exatamente como extraídos do modelo — preservados para que
# xl/drawings/_rels/drawing1.xml.rels (copiado do modelo, sem alteração)
# continue apontando para os arquivos certos.
ARQUIVOS_MEDIA = [
    "image1.png", "image2.svg", "image3.png", "image4.svg",
    "image5.png", "image6.svg", "image7.png", "image8.svg",
]

NOME_DRAWING_RESUMO = "drawing1.xml"
NOME_DRAWING_BASE_DETALHADA = "drawing2.xml"

# Placeholders presentes em drawing_resumo_template.xml (ver o texto original
# em cada card no arquivo-modelo, substituído por estes marcadores ao
# extrair o template).
PLACEHOLDERS = {
    "total_erp": "__TOTAL_ERP__",
    "total_banco": "__TOTAL_BANCO__",
    "conciliados": "__CONCILIADOS__",
    "revisao_manual": "__REVISAO_MANUAL__",
    "somente_banco": "__SOMENTE_BANCO__",
}

_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_TIPO_RELACAO_DRAWING = f"{_NS_REL_DOC}/drawing"
_NS_R_DECL = f' xmlns:r="{_NS_REL_DOC}"'

_CONTENT_TYPES_DEFAULTS = (
    ("png", "image/png"),
    ("svg", "image/svg+xml"),
)


def _ler_bytes(caminho: Path) -> bytes:
    return caminho.read_bytes()


def _montar_drawing_resumo(valores: dict) -> bytes:
    """Substitui os 5 placeholders do template pelos valores calculados nesta
    execução (nunca os valores fixos do arquivo-modelo)."""
    xml = (PASTA_ASSETS / "drawing_resumo_template.xml").read_text(encoding="utf-8")
    faltando = [chave for chave in PLACEHOLDERS if chave not in valores]
    if faltando:
        raise ValueError(f"Valores ausentes para o painel de cards: {faltando}")
    for chave, placeholder in PLACEHOLDERS.items():
        xml = xml.replace(placeholder, valores[chave])
    if any(placeholder in xml for placeholder in PLACEHOLDERS.values()):
        raise ValueError("Placeholder do template de cards não foi substituído — abortando para não gerar card em branco.")
    return xml.encode("utf-8")


def _resolver_nome_arquivo_sheet(partes: dict, titulo_aba: str) -> str:
    """Descobre, a partir de xl/workbook.xml e xl/_rels/workbook.xml.rels, o
    nome real do arquivo (ex.: "sheet1.xml") da aba com o título dado — nunca
    supõe uma numeração fixa."""
    workbook_xml = ET.fromstring(partes["xl/workbook.xml"])
    rid = None
    for sheet in workbook_xml.iter(f"{{{_NS_MAIN}}}sheet"):
        if sheet.get("name") == titulo_aba:
            rid = sheet.get(f"{{{_NS_REL_DOC}}}id")
            break
    if rid is None:
        raise ValueError(f"Aba '{titulo_aba}' não encontrada em xl/workbook.xml.")

    rels_xml = ET.fromstring(partes["xl/_rels/workbook.xml.rels"])
    for rel in rels_xml.iter(f"{{{_NS_PKG_REL}}}Relationship"):
        if rel.get("Id") == rid:
            destino = rel.get("Target")
            return destino.rsplit("/", 1)[-1]
    raise ValueError(f"Relationship '{rid}' não encontrada em xl/_rels/workbook.xml.rels.")


def _proximo_rid_livre(rels_xml_texto: str) -> str:
    usados = {int(numero) for numero in re.findall(r'Id="rId(\d+)"', rels_xml_texto)}
    numero = 1
    while numero in usados:
        numero += 1
    return f"rId{numero}"


def _garantir_rels_com_drawing(rels_existente: bytes, nome_drawing: str) -> tuple:
    """Retorna (rid, bytes_do_rels_atualizado), criando o arquivo .rels do
    zero se a planilha ainda não tiver um, ou acrescentando a relação (com um
    rId livre) se já existir por outro motivo."""
    if rels_existente is None:
        rid = "rId1"
        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{_NS_PKG_REL}">'
            f'<Relationship Id="{rid}" Type="{_TIPO_RELACAO_DRAWING}" Target="../drawings/{nome_drawing}"/>'
            "</Relationships>"
        )
        return rid, xml.encode("utf-8")

    texto = rels_existente.decode("utf-8")
    rid = _proximo_rid_livre(texto)
    nova_relacao = f'<Relationship Id="{rid}" Type="{_TIPO_RELACAO_DRAWING}" Target="../drawings/{nome_drawing}"/>'
    texto = texto.replace("</Relationships>", nova_relacao + "</Relationships>")
    return rid, texto.encode("utf-8")


def _inserir_drawing_no_sheet(xml_bytes: bytes, rid: str) -> bytes:
    texto = xml_bytes.decode("utf-8")
    if "</worksheet>" not in texto:
        raise ValueError("XML da planilha sem '</worksheet>' — estrutura inesperada, abortando injeção de cards.")

    if "xmlns:r=" not in texto:
        fechamento = texto.index(">", texto.index("<worksheet"))
        texto = texto[:fechamento] + _NS_R_DECL + texto[fechamento:]

    texto = texto.replace("</worksheet>", f'<drawing r:id="{rid}"/></worksheet>')
    return texto.encode("utf-8")


def _garantir_content_types(xml_bytes: bytes, nomes_drawings_novos: list) -> bytes:
    texto = xml_bytes.decode("utf-8")

    adicoes = "".join(
        f'<Default Extension="{extensao}" ContentType="{content_type}"/>'
        for extensao, content_type in _CONTENT_TYPES_DEFAULTS
        if f'Extension="{extensao}"' not in texto
    )
    adicoes += "".join(
        f'<Override PartName="/xl/drawings/{nome}" '
        'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
        for nome in nomes_drawings_novos
        if f"/xl/drawings/{nome}" not in texto
    )
    if not adicoes:
        return xml_bytes

    fechamento = texto.index(">", texto.index("<Types")) + 1
    texto = texto[:fechamento] + adicoes + texto[fechamento:]
    return texto.encode("utf-8")


def injetar_cards_e_icones(caminho_xlsx: Path, nome_aba_resumo: str, nome_aba_base_detalhada: str, valores_cards: dict) -> None:
    """Pós-processa `caminho_xlsx` (já salvo pelo openpyxl) acrescentando:

    - os 5 cards do painel executivo (formas + ícones do modelo) na aba
      `nome_aba_resumo`, com os valores de `valores_cards` (calculados a
      partir do resultado desta execução — nunca os do arquivo-modelo);
    - o pequeno selo decorativo do título "Base detalhada completa" na aba
      `nome_aba_base_detalhada` (estático, sem valor dinâmico).

    Nunca lê nem sobrescreve o arquivo-modelo em si.
    """
    with zipfile.ZipFile(caminho_xlsx, "r") as zip_leitura:
        partes = {info.filename: zip_leitura.read(info.filename) for info in zip_leitura.infolist()}

    nome_arquivo_resumo = _resolver_nome_arquivo_sheet(partes, nome_aba_resumo)
    nome_arquivo_base = _resolver_nome_arquivo_sheet(partes, nome_aba_base_detalhada)

    # 1) Cards do Resumo (com os valores desta execução).
    partes[f"xl/drawings/{NOME_DRAWING_RESUMO}"] = _montar_drawing_resumo(valores_cards)
    partes[f"xl/drawings/_rels/{NOME_DRAWING_RESUMO}.rels"] = _ler_bytes(PASTA_ASSETS / "drawing_resumo.xml.rels")
    for nome_media in ARQUIVOS_MEDIA:
        partes[f"xl/media/{nome_media}"] = _ler_bytes(PASTA_MEDIA / nome_media)

    caminho_sheet_resumo = f"xl/worksheets/{nome_arquivo_resumo}"
    caminho_rels_resumo = f"xl/worksheets/_rels/{nome_arquivo_resumo}.rels"
    rid_resumo, rels_resumo = _garantir_rels_com_drawing(partes.get(caminho_rels_resumo), NOME_DRAWING_RESUMO)
    partes[caminho_rels_resumo] = rels_resumo
    partes[caminho_sheet_resumo] = _inserir_drawing_no_sheet(partes[caminho_sheet_resumo], rid_resumo)

    # 2) Selo decorativo da Base Detalhada (estático, sem valores dinâmicos).
    partes[f"xl/drawings/{NOME_DRAWING_BASE_DETALHADA}"] = _ler_bytes(PASTA_ASSETS / "drawing_base_detalhada.xml")

    caminho_sheet_base = f"xl/worksheets/{nome_arquivo_base}"
    caminho_rels_base = f"xl/worksheets/_rels/{nome_arquivo_base}.rels"
    rid_base, rels_base = _garantir_rels_com_drawing(partes.get(caminho_rels_base), NOME_DRAWING_BASE_DETALHADA)
    partes[caminho_rels_base] = rels_base
    partes[caminho_sheet_base] = _inserir_drawing_no_sheet(partes[caminho_sheet_base], rid_base)

    # 3) Content types (idempotente — só acrescenta o que ainda não existir).
    partes["[Content_Types].xml"] = _garantir_content_types(
        partes["[Content_Types].xml"], [NOME_DRAWING_RESUMO, NOME_DRAWING_BASE_DETALHADA]
    )

    caminho_temporario = caminho_xlsx.with_suffix(".tmp.xlsx")
    with zipfile.ZipFile(caminho_temporario, "w", zipfile.ZIP_DEFLATED) as zip_escrita:
        for nome, conteudo in partes.items():
            zip_escrita.writestr(nome, conteudo)
    caminho_temporario.replace(caminho_xlsx)
