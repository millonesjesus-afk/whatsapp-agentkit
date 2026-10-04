# agent/meta_timezones.py — 2026-10-04
#
# La cuenta de WhatsApp Business (WABA) informa su zona horaria como un id
# numérico (`GET /{waba_id}?fields=timezone_id`), no como nombre. Meta publica
# la tabla completa (~590 ids) en
# developers.facebook.com/documentation/business-messaging/whatsapp/timezone-ids/
# — acá solo van las zonas que un negocio de este sistema puede tener
# realisticamente; un id que no esté se informa tal cual y la zona se elige a
# mano (nunca se adivina). Los valores son nombres IANA que `zoneinfo` entiende.

TIMEZONE_ID_A_IANA: dict[str, str] = {
    "103": "America/Lima",
    "43": "America/Bogota",
    "51": "America/Guayaquil",
    "94": "America/Mexico_City",
    "41": "America/Santiago",
    "10": "America/Argentina/Buenos_Aires",
    "479": "America/Buenos_Aires",
    "25": "America/Sao_Paulo",
    "139": "America/Caracas",
    "21": "America/La_Paz",
    "138": "America/Montevideo",
    "111": "America/Asuncion",
    "102": "America/Panama",
    "44": "America/Costa_Rica",
    "61": "America/Guatemala",
    "131": "America/El_Salvador",
    "63": "America/Tegucigalpa",
    "97": "America/Managua",
    "49": "America/Santo_Domingo",
    "107": "America/Puerto_Rico",
    "232": "America/Havana",
    "7": "America/New_York",
    "6": "America/Chicago",
    "2": "America/Denver",
    "1": "America/Los_Angeles",
    "55": "Europe/Madrid",
    "474": "UTC",
}


def zona_iana_de_meta(timezone_id: object) -> str | None:
    """Nombre IANA de un `timezone_id` de Meta, o None si no está en la tabla."""
    return TIMEZONE_ID_A_IANA.get(str(timezone_id).strip())
