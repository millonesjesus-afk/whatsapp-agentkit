# tests/test_tools_catalogo_contexto.py — obtener_contexto_relevante ahora
# limita a 5 productos (antes 8) en el contexto que se le arma a Gabi.
#
# Pedido explícito del usuario (2026-09-17), revisando su consumo real de
# la API: 5 opciones ya alcanzan para orientar a un cliente, y reducir el
# tamaño del contexto dinámico (NO cacheable — cambia en cada turno) baja
# proporcionalmente el costo de cada llamada. Los otros llamadores de
# buscar_productos (ej. el buscador del panel, dashboard.py) siguen en 8 —
# el límite nuevo es propio de este punto de entrada, no del default de
# buscar_productos.

from agent import memory as mem
from agent.tools import obtener_contexto_relevante


async def test_contexto_de_gabi_trae_como_maximo_5_productos():
    negocio = await mem.crear_negocio("Negocio Catalogo Contexto", "g-ctx-1")
    for i in range(8):
        await mem.crear_producto(
            {
                "tipo": "terma", "sub_tipo": "a gas", "marca": f"Marca{i}",
                "descripcion": f"Terma modelo {i}", "codigo_hana": f"HANA-CTX-{i:03d}",
                "precio": str(400 + i * 10),
            },
            autor="test", negocio_id=negocio["id"],
        )

    contexto = await obtener_contexto_relevante("busco una terma a gas", negocio["id"], "g-ctx-1")

    # El contexto numera los productos "1." a "N." — con 8 productos
    # creados pero el límite en 5, la numeración nunca debe llegar a "6."
    assert "5. " in contexto
    assert "6. " not in contexto
