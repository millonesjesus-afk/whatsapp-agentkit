# tests/test_adjuntos_chat_tamano.py — hallazgo del usuario (2026-09-16):
# "no se puede adjuntar documentos... en los chats" — un PDF real (catálogo/
# proforma) de más de 20MB se rechazaba, aunque Meta acepta documentos hasta
# 100MB. `enviar_archivo_chat` (agent/dashboard.py) usaba un solo tope
# (TAMANO_MAXIMO_ARCHIVO_MB=20) para PDF/JPG/JPEG/PNG por igual — se separó
# en `_tamano_maximo_para_extension`: documentos hasta 75MB (confirmado con
# el usuario, margen bajo el límite real de Meta), imágenes en 5MB (el
# límite real de Meta para imágenes, no un número arbitrario).

from agent.dashboard import (
    EXTENSIONES_ARCHIVO_PERMITIDAS,
    TAMANO_MAXIMO_DOCUMENTO_MB,
    TAMANO_MAXIMO_IMAGEN_MB,
    _tamano_maximo_para_extension,
)


def test_pdf_usa_el_tope_de_documento():
    assert _tamano_maximo_para_extension(".pdf") == TAMANO_MAXIMO_DOCUMENTO_MB
    assert TAMANO_MAXIMO_DOCUMENTO_MB == 75


def test_imagenes_usan_el_tope_de_imagen_no_el_de_documento():
    assert _tamano_maximo_para_extension(".jpg") == TAMANO_MAXIMO_IMAGEN_MB
    assert _tamano_maximo_para_extension(".jpeg") == TAMANO_MAXIMO_IMAGEN_MB
    assert _tamano_maximo_para_extension(".png") == TAMANO_MAXIMO_IMAGEN_MB
    assert TAMANO_MAXIMO_IMAGEN_MB == 5


def test_un_pdf_de_30mb_ya_no_se_rechazaria_hoy_se_rechazaba():
    """El caso real que reportó el usuario: un PDF de +20MB (pero bajo 75MB)
    debe pasar el chequeo de tamaño hoy — antes de este fix, cualquier PDF
    de más de 20MB era rechazado sin importar que Meta lo aceptara."""
    treinta_mb_en_bytes = 30 * 1024 * 1024
    tope = _tamano_maximo_para_extension(".pdf")
    assert treinta_mb_en_bytes <= tope * 1024 * 1024


def test_un_pdf_de_80mb_sigue_rechazandose():
    ochenta_mb_en_bytes = 80 * 1024 * 1024
    tope = _tamano_maximo_para_extension(".pdf")
    assert ochenta_mb_en_bytes > tope * 1024 * 1024


# ── Gate 2026-09-23: Word/Excel/PowerPoint/texto — mismo set que WhatsApp
# Cloud API acepta para mensajes de documento (referencia oficial de Meta).
# Antes de este fix, `_tamano_maximo_para_extension` solo reconocía ".pdf"
# como documento — cualquier extensión nueva caía por descarte en el tope
# de 5MB de imagen, mucho más bajo de lo que Meta realmente permite.

def test_word_excel_powerpoint_texto_estan_permitidos():
    for extension in (".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt"):
        assert extension in EXTENSIONES_ARCHIVO_PERMITIDAS


def test_word_excel_powerpoint_texto_usan_el_tope_de_documento_no_el_de_imagen():
    for extension in (".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt"):
        assert _tamano_maximo_para_extension(extension) == TAMANO_MAXIMO_DOCUMENTO_MB


def test_un_docx_de_30mb_pasa_el_tope_hoy_antes_hubiera_fallado_como_imagen():
    """Antes del fix, un .docx de 30MB se hubiera rechazado por el tope de
    5MB de imagen (caía por descarte) aunque Meta acepta documentos hasta
    100MB — mismo tipo de hallazgo real que el del PDF (ver arriba)."""
    treinta_mb_en_bytes = 30 * 1024 * 1024
    tope = _tamano_maximo_para_extension(".docx")
    assert treinta_mb_en_bytes <= tope * 1024 * 1024
