
from pathlib import Path
import hashlib
import math

import pandas as pd
import streamlit as st

from modules.excel_manager import (
    COLUMNAS_TUU,
    cargar_excel,
    guardar_excel,
    crear_ruta_trabajo
)

from modules.duplicate_detector import (
    detectar_grupos_duplicados,
    normalizar_texto,
    normalizar_codigo
)

from modules.product_form import mostrar_formulario_producto


# ==========================================
# CONFIGURACION GENERAL
# ==========================================

st.set_page_config(
    page_title="Gestor de Catálogo TUU",
    page_icon="📦",
    layout="wide"
)

LIMITE_HISTORIAL = 30

st.title("📦 Gestor de Catálogo TUU")
st.caption("Administración de productos para minimarket")


# ==========================================
# ESTADO DE SESION
# ==========================================

VALORES_INICIALES = {
    "vista": "principal",
    "archivo_id": None,
    "df_productos": None,
    "ruta_trabajo": None,
    "version_editor": 0,
    "version_formulario": 0,
    "indice_edicion": None,
    "historial": [],
    "posicion_historial": 0,
    "grupos_duplicados": None,
    "producto_eliminar": None,
    "datos_pendientes": None,
    "modo_pendiente": None,
    "indice_pendiente": None,
    "mensaje": None,
    "version_tabla": 0,
    "filtro_edicion": "Todos los productos",
    "busqueda_edicion": "",
}

for clave, valor in VALORES_INICIALES.items():
    if clave not in st.session_state:
        st.session_state[clave] = valor


# ==========================================
# FUNCIONES GENERALES
# ==========================================

def limpiar_pendientes():
    st.session_state["datos_pendientes"] = None
    st.session_state["modo_pendiente"] = None
    st.session_state["indice_pendiente"] = None


def limpiar_duplicados():
    st.session_state["grupos_duplicados"] = None
    st.session_state["producto_eliminar"] = None


def cambiar_vista(vista, indice=None):
    st.session_state["vista"] = vista
    st.session_state["indice_edicion"] = indice
    st.session_state["version_formulario"] += 1
    limpiar_pendientes()


def iniciar_historial(df):
    st.session_state["historial"] = [
        df.copy(deep=True)
    ]
    st.session_state["posicion_historial"] = 0


def registrar_historial(df):
    historial = st.session_state["historial"]
    posicion = st.session_state["posicion_historial"]

    historial = historial[:posicion + 1]
    historial.append(df.copy(deep=True))

    if len(historial) > LIMITE_HISTORIAL + 1:
        historial.pop(0)

    st.session_state["historial"] = historial
    st.session_state["posicion_historial"] = (
        len(historial) - 1
    )


def guardar_cambios(df_nuevo):
    df_nuevo = (
        df_nuevo[COLUMNAS_TUU]
        .copy()
        .reset_index(drop=True)
        .fillna("")
        .astype(str)
    )

    correcto, error = guardar_excel(
        df_nuevo,
        st.session_state["ruta_trabajo"]
    )

    if correcto:
        st.session_state["df_productos"] = df_nuevo
        registrar_historial(df_nuevo)

        st.session_state["version_editor"] += 1
        st.session_state["version_tabla"] += 1

        limpiar_duplicados()

    return correcto, error


def mover_historial(direccion):
    historial = st.session_state["historial"]
    posicion = st.session_state["posicion_historial"]
    nueva_posicion = posicion + direccion

    if not 0 <= nueva_posicion < len(historial):
        return False, "No hay más cambios disponibles."

    restaurado = historial[
        nueva_posicion
    ].copy(deep=True)

    correcto, error = guardar_excel(
        restaurado,
        st.session_state["ruta_trabajo"]
    )

    if correcto:
        st.session_state["df_productos"] = restaurado
        st.session_state["posicion_historial"] = (
            nueva_posicion
        )

        st.session_state["version_editor"] += 1
        st.session_state["version_tabla"] += 1

        limpiar_duplicados()
        limpiar_pendientes()

    return correcto, error


# ==========================================
# VALIDACION DEL CATALOGO
# ==========================================

def obtener_problemas(producto):
    """
    Revisa únicamente los campos
    obligatorios para TUU.
    """

    problemas = []

    nombre = str(
        producto["NOMBRE*"]
    ).strip()

    precio = str(
        producto["PRECIO*"]
    ).strip()

    exento = str(
        producto["¿EXENTO?*"]
    ).strip()

    habilitado = str(
        producto["¿HABILITADO?*"]
    ).strip()

    if not nombre:
        problemas.append("Nombre vacío")

    if not precio:
        problemas.append("Precio vacío")
    else:
        try:
            valor = float(precio)

            if not math.isfinite(valor):
                problemas.append(
                    "Precio no válido"
                )
            elif valor < 0:
                problemas.append(
                    "Precio negativo"
                )

        except ValueError:
            problemas.append(
                "Precio no numérico"
            )

    if exento not in ("S", "N"):
        problemas.append(
            "Exento debe ser S o N"
        )

    if habilitado not in ("S", "N"):
        problemas.append(
            "Habilitado debe ser S o N"
        )

    return problemas


def validar_catalogo(df):
    errores = []

    for indice, producto in df.iterrows():
        problemas = obtener_problemas(
            producto
        )

        if problemas:
            nombre = str(
                producto["NOMBRE*"]
            ).strip()

            errores.append({
                "Fila Excel": indice + 2,
                "Producto": (
                    nombre or "(Sin nombre)"
                ),
                "Problemas": ", ".join(problemas)
            })

    return errores


def calcular_avance(df):
    total = len(df)
    errores = validar_catalogo(df)

    pendientes = len(errores)
    completos = total - pendientes

    porcentaje = (
        (completos / total) * 100
        if total > 0 else 0.0
    )

    return {
        "total": total,
        "completos": completos,
        "pendientes": pendientes,
        "porcentaje": porcentaje,
        "errores": errores
    }


# ==========================================
# FILTROS DE EDICION RAPIDA
# ==========================================

OPCIONES_FILTRO = [
    "Todos los productos",
    "Productos completos",
    "Productos incompletos",
    "Sin nombre",
    "Sin precio",
    "Sin SKU",
    "Sin código de barras",
    "Sin descripción",
    "Sin marca",
    "Sin categoría",
    "Sin peso",
    "Sin precio de costo",
    "Exento sin definir",
    "Habilitado sin definir",
]

CAMPOS_FALTANTES = {
    "Sin nombre": "NOMBRE*",
    "Sin precio": "PRECIO*",
    "Sin SKU": "CÓDIGO SKU",
    "Sin código de barras": "CÓDIGO DE BARRAS",
    "Sin descripción": "Descripción",
    "Sin marca": "MARCAS",
    "Sin categoría": "CATEGORIAS",
    "Sin peso": "PESO",
    "Sin precio de costo": "PRECIO COSTO",
}


def filtrar_productos(df, filtro, busqueda):
    """
    Mantiene los índices originales
    de los productos.

    Esto permite guardar correctamente
    las modificaciones de una tabla filtrada.
    """

    resultado = df.copy()

    if filtro == "Productos completos":
        mascara = resultado.apply(
            lambda producto: (
                len(obtener_problemas(producto)) == 0
            ),
            axis=1
        )

        resultado = resultado.loc[mascara]

    elif filtro == "Productos incompletos":
        mascara = resultado.apply(
            lambda producto: (
                len(obtener_problemas(producto)) > 0
            ),
            axis=1
        )

        resultado = resultado.loc[mascara]

    elif filtro in CAMPOS_FALTANTES:
        columna = CAMPOS_FALTANTES[filtro]

        mascara = (
            resultado[columna]
            .fillna("")
            .astype(str)
            .str.strip()
            .eq("")
        )

        if filtro == "Sin precio":
            # Incluye precios vacíos, inválidos
            # o negativos para facilitar revisión.
            mascara = resultado.apply(
                lambda producto: any(
                    problema.startswith("Precio")
                    for problema in obtener_problemas(
                        producto
                    )
                ),
                axis=1
            )

        resultado = resultado.loc[mascara]

    elif filtro == "Exento sin definir":
        mascara = ~resultado[
            "¿EXENTO?*"
        ].astype(str).str.strip().isin(["S", "N"])

        resultado = resultado.loc[mascara]

    elif filtro == "Habilitado sin definir":
        mascara = ~resultado[
            "¿HABILITADO?*"
        ].astype(str).str.strip().isin(["S", "N"])

        resultado = resultado.loc[mascara]

    texto = busqueda.strip()

    if texto:
        mascara_busqueda = (
            resultado["NOMBRE*"]
            .str.contains(
                texto,
                case=False,
                regex=False,
                na=False
            )
            |
            resultado["CÓDIGO SKU"]
            .str.contains(
                texto,
                case=False,
                regex=False,
                na=False
            )
            |
            resultado["CÓDIGO DE BARRAS"]
            .str.contains(
                texto,
                case=False,
                regex=False,
                na=False
            )
        )

        resultado = resultado.loc[
            mascara_busqueda
        ]

    return resultado


def guardar_edicion_filtrada(
    df_original,
    df_mostrado,
    df_editado
):
    """
    Guarda los cambios en las filas
    originales del catálogo.

    No modifica las filas ocultas
    por el filtro.
    """

    df_nuevo = df_original.copy()

    if len(df_mostrado) != len(df_editado):
        return (
            False,
            "No se puede cambiar la cantidad de "
            "filas mientras hay un filtro activo."
        )

    for indice_original in df_mostrado.index:
        for columna in COLUMNAS_TUU:
            valor_anterior = (
                df_mostrado.at[
                    indice_original,
                    columna
                ]
            )

            valor_nuevo = (
                df_editado.at[
                    indice_original,
                    columna
                ]
            )

            if pd.isna(valor_nuevo):
                valor_nuevo = ""

            if str(valor_anterior) != str(valor_nuevo):
                df_nuevo.at[
                    indice_original,
                    columna
                ] = str(valor_nuevo)

    return guardar_cambios(df_nuevo)


# ==========================================
# COMPROBAR DUPLICADOS AL GUARDAR
# ==========================================

def buscar_coincidencias(datos, df, excluir=None):
    coincidencias = []

    nombre = normalizar_texto(datos["NOMBRE*"])
    sku = normalizar_codigo(datos["CÓDIGO SKU"])
    ean = normalizar_codigo(
        datos["CÓDIGO DE BARRAS"]
    )

    for indice, producto in df.iterrows():
        if indice == excluir:
            continue

        motivos = []

        nombre_actual = normalizar_texto(
            producto["NOMBRE*"]
        )

        sku_actual = normalizar_codigo(
            producto["CÓDIGO SKU"]
        )

        ean_actual = normalizar_codigo(
            producto["CÓDIGO DE BARRAS"]
        )

        if sku and sku == sku_actual:
            motivos.append("SKU repetido")

        if ean and ean == ean_actual:
            motivos.append(
                "Código de barras repetido"
            )

        if nombre and nombre == nombre_actual:
            motivos.append("Nombre equivalente")

        if motivos:
            coincidencias.append({
                "indice": indice,
                "nombre": producto["NOMBRE*"],
                "motivos": motivos
            })

    return coincidencias


# ==========================================
# CREAR O EDITAR PRODUCTOS
# ==========================================

def aplicar_producto(datos, modo, indice=None):
    df_nuevo = st.session_state[
        "df_productos"
    ].copy()

    if modo == "crear":
        nuevo = pd.DataFrame(
            [datos],
            columns=COLUMNAS_TUU
        )

        df_nuevo = pd.concat(
            [df_nuevo, nuevo],
            ignore_index=True
        )

    elif modo == "editar":
        if indice is None or not (
            0 <= indice < len(df_nuevo)
        ):
            return False, "Producto no encontrado."

        for columna in COLUMNAS_TUU:
            df_nuevo.at[
                indice,
                columna
            ] = datos[columna]

    else:
        return False, "Operación no válida."

    return guardar_cambios(df_nuevo)


def finalizar_guardado(datos, modo, indice=None):
    correcto, error = aplicar_producto(
        datos,
        modo,
        indice
    )

    if correcto:
        cambiar_vista("principal")

        st.session_state["mensaje"] = (
            "Producto guardado correctamente."
        )

        st.rerun()
    else:
        st.error(error)


# ==========================================
# FORMULARIO COMPARTIDO
# ==========================================

def mostrar_vista_formulario(modo, indice=None):
    df = st.session_state["df_productos"]

    producto = None

    if modo == "editar":
        if indice is None or not (
            0 <= indice < len(df)
        ):
            st.error("El producto ya no existe.")

            if st.button("← Volver al catálogo"):
                cambiar_vista("principal")
                st.rerun()

            return

        producto = df.iloc[indice]

    col_titulo, col_volver = st.columns([5, 1])

    with col_titulo:
        if modo == "crear":
            st.subheader("➕ Nuevo Producto")
        else:
            st.subheader("✏️ Editar Producto")
            st.caption(
                f"Producto: {producto['NOMBRE*']}"
            )

    with col_volver:
        if st.button(
            "← Volver",
            use_container_width=True
        ):
            cambiar_vista("principal")
            st.rerun()

    with st.container(border=True):
        datos, enviado = mostrar_formulario_producto(
            producto=producto,
            clave=(
                f"{modo}_{indice}_"
                f"{st.session_state['version_formulario']}"
            )
        )

    if enviado:
        coincidencias = buscar_coincidencias(
            datos,
            df,
            excluir=(
                indice if modo == "editar"
                else None
            )
        )

        if coincidencias:
            st.session_state["datos_pendientes"] = (
                datos.copy()
            )
            st.session_state["modo_pendiente"] = modo
            st.session_state["indice_pendiente"] = indice

        else:
            finalizar_guardado(
                datos,
                modo,
                indice
            )

    pendientes = st.session_state["datos_pendientes"]

    if pendientes is not None:
        coincidencias = buscar_coincidencias(
            pendientes,
            st.session_state["df_productos"],
            excluir=(
                indice if modo == "editar"
                else None
            )
        )

        st.warning(
            "⚠️ Se encontraron posibles duplicados. "
            "Revisa antes de guardar."
        )

        for coincidencia in coincidencias:
            st.write(
                f"**{coincidencia['nombre']}** — "
                + ", ".join(
                    coincidencia["motivos"]
                )
            )

        col_si, col_no = st.columns(2)

        with col_si:
            if st.button(
                "Guardar de todas formas",
                type="primary",
                use_container_width=True
            ):
                finalizar_guardado(
                    pendientes,
                    st.session_state["modo_pendiente"],
                    st.session_state["indice_pendiente"]
                )

        with col_no:
            if st.button(
                "Cancelar guardado",
                use_container_width=True
            ):
                limpiar_pendientes()
                st.rerun()


# ==========================================
# IMPORTAR CATALOGO
# ==========================================

with st.expander(
    "📂 Archivo Excel del catálogo",
    expanded=True
):
    archivo = st.file_uploader(
        "Selecciona tu archivo Excel de TUU",
        type=["xlsx"]
    )

    if archivo is not None:
        identificador = hashlib.sha256(
            archivo.getvalue()
        ).hexdigest()

        if (
            st.session_state["archivo_id"]
            != identificador
        ):
            df_importado, error = cargar_excel(
                archivo
            )

            if error:
                st.error(error)
                st.stop()

            ruta = crear_ruta_trabajo(
                archivo.name
            )

            correcto, error = guardar_excel(
                df_importado,
                ruta
            )

            if not correcto:
                st.error(error)
                st.stop()

            df_importado = (
                df_importado.copy()
                .reset_index(drop=True)
                .fillna("")
                .astype(str)
            )

            st.session_state["archivo_id"] = (
                identificador
            )
            st.session_state["df_productos"] = (
                df_importado
            )
            st.session_state["ruta_trabajo"] = str(ruta)

            st.session_state["version_editor"] += 1
            st.session_state["version_tabla"] += 1

            st.session_state["filtro_edicion"] = (
                "Todos los productos"
            )
            st.session_state["busqueda_edicion"] = ""

            iniciar_historial(df_importado)
            limpiar_duplicados()
            cambiar_vista("principal")

            st.success(
                "Catálogo importado correctamente."
            )


if st.session_state["df_productos"] is None:
    st.info(
        "Importa un archivo Excel para comenzar."
    )
    st.stop()


# ==========================================
# INFORMACION GENERAL
# ==========================================

df = st.session_state["df_productos"]

col_total, col_ruta = st.columns([1, 4])

with col_total:
    st.metric("Total de productos", len(df))

with col_ruta:
    st.caption(
        "Copia de trabajo: "
        + str(st.session_state["ruta_trabajo"])
    )

if st.session_state["mensaje"]:
    st.success(st.session_state["mensaje"])
    st.session_state["mensaje"] = None

st.divider()


# ==========================================
# VISTA INDEPENDIENTE DEL FORMULARIO
# ==========================================

vista = st.session_state["vista"]

if vista in ("crear", "editar"):
    mostrar_vista_formulario(
        modo=vista,
        indice=st.session_state["indice_edicion"]
    )

    st.stop()


# ==========================================
# SECCION 1: CATALOGO
# ==========================================

with st.expander(
    "📋 Catálogo de productos",
    expanded=True
):
    col_titulo, col_nuevo = st.columns([5, 1])

    with col_titulo:
        st.caption(
            "Busca, selecciona y edita "
            "los productos de tu catálogo."
        )

    with col_nuevo:
        if st.button(
            "➕ Nuevo Producto",
            type="primary",
            use_container_width=True
        ):
            cambiar_vista("crear")
            st.rerun()

    busqueda = st.text_input(
        "🔎 Buscar producto",
        placeholder=(
            "Nombre, SKU o código de barras"
        ),
        key="busqueda_catalogo"
    )

    df_filtrado = st.session_state[
        "df_productos"
    ]

    if busqueda.strip():
        texto = busqueda.strip()

        mascara = (
            df_filtrado["NOMBRE*"]
            .str.contains(
                texto,
                case=False,
                regex=False,
                na=False
            )
            |
            df_filtrado["CÓDIGO SKU"]
            .str.contains(
                texto,
                case=False,
                regex=False,
                na=False
            )
            |
            df_filtrado["CÓDIGO DE BARRAS"]
            .str.contains(
                texto,
                case=False,
                regex=False,
                na=False
            )
        )

        df_filtrado = df_filtrado.loc[mascara]

    st.caption(
        f"Mostrando {len(df_filtrado)} "
        f"de {len(df)} productos"
    )

    columnas_visibles = [
        "NOMBRE*",
        "PRECIO*",
        "CÓDIGO SKU",
        "CÓDIGO DE BARRAS",
        "MARCAS",
        "CATEGORIAS"
    ]

    tabla_catalogo = df_filtrado[
        columnas_visibles
    ].copy()

    indices_reales = list(
        tabla_catalogo.index
    )

    tabla_catalogo = (
        tabla_catalogo.reset_index(drop=True)
    )

    clave_busqueda = hashlib.md5(
        busqueda.strip().lower().encode("utf-8")
    ).hexdigest()[:10]

    seleccion = st.dataframe(
        tabla_catalogo,
        hide_index=True,
        width="stretch",
        height=400,
        on_select="rerun",
        selection_mode="single-row",
        key=(
            f"tabla_catalogo_"
            f"{st.session_state['version_tabla']}_"
            f"{clave_busqueda}"
        )
    )

    filas_seleccionadas = (
        seleccion.selection.rows
    )

    indice_real = None

    if filas_seleccionadas:
        posicion_fila = filas_seleccionadas[0]

        if 0 <= posicion_fila < len(indices_reales):
            indice_real = indices_reales[
                posicion_fila
            ]

    col_editar, col_seleccion = st.columns([2, 5])

    with col_editar:
        if st.button(
            "✏️ Editar seleccionado",
            disabled=indice_real is None,
            type="primary",
            use_container_width=True
        ):
            cambiar_vista(
                "editar",
                indice_real
            )
            st.rerun()

    with col_seleccion:
        if indice_real is not None:
            producto = (
                st.session_state["df_productos"]
                .iloc[indice_real]
            )

            st.caption(
                f"Seleccionado: {producto['NOMBRE*']}"
            )
        else:
            st.caption(
                "Selecciona una fila para editar."
            )


# ==========================================
# SECCION 2: EDICION RAPIDA CON FILTROS
# ==========================================

with st.expander(
    "📝 Edición rápida de la planilla",
    expanded=True
):
    st.caption(
        "Filtra los productos y edita directamente "
        "sus datos. Los cambios se guardan "
        "automáticamente."
    )

    # --------------------------------------
    # FILTROS
    # --------------------------------------

    col_filtro, col_buscar = st.columns([2, 3])

    with col_filtro:
        filtro = st.selectbox(
            "Filtrar productos",
            options=OPCIONES_FILTRO,
            key="filtro_edicion"
        )

    with col_buscar:
        busqueda_rapida = st.text_input(
            "Buscar dentro de los resultados",
            placeholder=(
                "Nombre, SKU o código de barras"
            ),
            key="busqueda_edicion"
        )

    df_actual = st.session_state[
        "df_productos"
    ]

    df_mostrado = filtrar_productos(
        df_actual,
        filtro,
        busqueda_rapida
    )

    st.caption(
        f"Mostrando {len(df_mostrado)} "
        f"de {len(df_actual)} productos"
    )

    if filtro in CAMPOS_FALTANTES:
        if filtro not in ("Sin nombre", "Sin precio"):
            st.caption(
                "Este campo es opcional para la "
                "validación básica de TUU, pero "
                "puedes revisarlo para mejorar "
                "tu catálogo."
            )

    # --------------------------------------
    # CONTROLES
    # --------------------------------------

    historial = st.session_state["historial"]
    posicion = st.session_state[
        "posicion_historial"
    ]

    # Solo permitimos agregar/eliminar filas
    # cuando no existe ningún filtro.
    vista_completa = (
        filtro == "Todos los productos"
        and not busqueda_rapida.strip()
    )

    col_agregar, col_atras, col_adelante, col_estado = (
        st.columns([1.7, 1.3, 1.3, 3])
    )

    with col_agregar:
        if st.button(
            "➕ Agregar fila",
            type="primary",
            use_container_width=True,
            disabled=not vista_completa
        ):
            df_nuevo = df_actual.copy()

            nueva_fila = {
                columna: ""
                for columna in COLUMNAS_TUU
            }

            nueva_fila["¿EXENTO?*"] = "N"
            nueva_fila["¿HABILITADO?*"] = "S"

            df_nuevo = pd.concat(
                [
                    df_nuevo,
                    pd.DataFrame(
                        [nueva_fila],
                        columns=COLUMNAS_TUU
                    )
                ],
                ignore_index=True
            )

            correcto, error = guardar_cambios(
                df_nuevo
            )

            if correcto:
                st.toast(
                    "Fila agregada al final",
                    icon="✅"
                )
                st.rerun()
            else:
                st.error(error)

    with col_atras:
        if st.button(
            "↶ Deshacer",
            disabled=posicion == 0,
            use_container_width=True
        ):
            correcto, error = mover_historial(-1)

            if correcto:
                st.rerun()
            else:
                st.error(error)

    with col_adelante:
        if st.button(
            "↷ Rehacer",
            disabled=(
                posicion >= len(historial) - 1
            ),
            use_container_width=True
        ):
            correcto, error = mover_historial(1)

            if correcto:
                st.rerun()
            else:
                st.error(error)

    with col_estado:
        st.caption(
            f"{posicion} para deshacer | "
            f"{len(historial) - posicion - 1} "
            "para rehacer"
        )

    # --------------------------------------
    # TABLA EDITABLE
    # --------------------------------------

    if df_mostrado.empty:
        st.info(
            "No se encontraron productos "
            "con los filtros seleccionados."
        )

    else:
        version = st.session_state[
            "version_editor"
        ]

        # Clave diferente por filtro/búsqueda
        # para evitar estados anteriores
        # del editor.
        identidad_filtro = (
            f"{filtro}|{busqueda_rapida}"
        )

        clave_filtro = hashlib.md5(
            identidad_filtro.encode("utf-8")
        ).hexdigest()[:10]

        df_editado = st.data_editor(
            df_mostrado.copy(),
            width="stretch",
            hide_index=True,
            num_rows=(
                "dynamic"
                if vista_completa
                else "fixed"
            ),
            key=(
                f"editor_productos_"
                f"{version}_{clave_filtro}"
            )
        )

        if not df_editado.equals(df_mostrado):

            if vista_completa:
                # Sin filtros, se puede agregar,
                # editar o eliminar filas.
                correcto, error = guardar_cambios(
                    df_editado
                )

            else:
                # Con filtros, solo se modifican
                # las filas originales visibles.
                correcto, error = (
                    guardar_edicion_filtrada(
                        df_actual,
                        df_mostrado,
                        df_editado
                    )
                )

            if correcto:
                st.toast(
                    "Cambios guardados",
                    icon="✅"
                )
                st.rerun()
            else:
                st.error(error)

        else:
            st.caption(
                "Todos los cambios están guardados."
            )

    if not vista_completa:
        st.info(
            "Estás trabajando con una vista filtrada. "
            "Puedes editar las celdas, pero para "
            "agregar o eliminar filas debes "
            "seleccionar «Todos los productos» "
            "y limpiar la búsqueda."
        )

    else:
        st.info(
            "Puedes editar, agregar o eliminar "
            "filas directamente en la tabla. "
            "Los cambios se guardan automáticamente."
        )


# ==========================================
# SECCION 3: DUPLICADOS
# ==========================================

with st.expander(
    "🔎 Revisión de duplicados",
    expanded=True
):
    st.caption(
        "La detección es manual. "
        "No se eliminarán productos automáticamente."
    )

    if st.button(
        "🔍 Analizar duplicados",
        type="primary"
    ):
        with st.spinner(
            "Analizando productos..."
        ):
            grupos = detectar_grupos_duplicados(
                st.session_state["df_productos"]
            )

        st.session_state[
            "grupos_duplicados"
        ] = grupos

        st.session_state[
            "producto_eliminar"
        ] = None

    grupos = st.session_state[
        "grupos_duplicados"
    ]

    if grupos is None:
        st.info(
            "Presiona Analizar duplicados "
            "para revisar el catálogo."
        )

    elif not grupos:
        st.success(
            "No se encontraron duplicados."
        )

    else:
        total = sum(
            grupo["cantidad"]
            for grupo in grupos
        )

        st.warning(
            f"Se encontraron {len(grupos)} "
            f"grupos con {total} registros "
            "que requieren revisión."
        )

        for grupo in grupos:
            with st.container(border=True):
                st.markdown(
                    f"### Grupo {grupo['grupo']} "
                    f"— {grupo['cantidad']} productos"
                )

                st.caption(
                    "Motivo: "
                    + ", ".join(grupo["motivos"])
                )

                for producto in grupo["productos"]:
                    indice = producto["indice"]

                    st.markdown(
                        f"**{producto['nombre']}**"
                    )

                    st.caption(
                        f"Fila Excel: "
                        f"{producto['fila_excel']} | "
                        f"SKU: "
                        f"{producto['sku'] or 'Sin SKU'} | "
                        f"EAN: "
                        f"{producto['ean'] or 'Sin EAN'} | "
                        f"Precio: "
                        f"{producto['precio'] or 'Sin precio'}"
                    )

                    col_editar, col_eliminar, _ = (
                        st.columns([1, 1, 4])
                    )

                    with col_editar:
                        if st.button(
                            "✏️ Editar",
                            key=f"dup_editar_{indice}",
                            use_container_width=True
                        ):
                            cambiar_vista(
                                "editar",
                                indice
                            )
                            st.rerun()

                    with col_eliminar:
                        if st.button(
                            "❌ Eliminar",
                            key=f"dup_eliminar_{indice}",
                            use_container_width=True
                        ):
                            st.session_state[
                                "producto_eliminar"
                            ] = indice
                            st.rerun()

                    if (
                        st.session_state[
                            "producto_eliminar"
                        ] == indice
                    ):
                        st.error(
                            "¿Confirmas la eliminación "
                            "de este producto?"
                        )

                        st.caption(
                            "Puedes recuperarlo "
                            "con Deshacer."
                        )

                        col_si, col_no = (
                            st.columns(2)
                        )

                        with col_si:
                            if st.button(
                                "Sí, eliminar",
                                type="primary",
                                key=f"si_eliminar_{indice}"
                            ):
                                df_nuevo = (
                                    st.session_state[
                                        "df_productos"
                                    ]
                                    .drop(index=indice)
                                    .reset_index(drop=True)
                                )

                                correcto, error = (
                                    guardar_cambios(
                                        df_nuevo
                                    )
                                )

                                if correcto:
                                    st.toast(
                                        "Producto eliminado",
                                        icon="✅"
                                    )
                                    st.rerun()
                                else:
                                    st.error(error)

                        with col_no:
                            if st.button(
                                "Cancelar",
                                key=f"no_eliminar_{indice}"
                            ):
                                st.session_state[
                                    "producto_eliminar"
                                ] = None
                                st.rerun()

                    st.divider()


# ==========================================
# SECCION 4: GUARDAR COMO EXCEL
# ==========================================

with st.expander(
    "💾 Guardar como Excel",
    expanded=True
):
    ruta_trabajo = Path(
        st.session_state["ruta_trabajo"]
    )

    avance = calcular_avance(
        st.session_state["df_productos"]
    )

    total = avance["total"]
    completos = avance["completos"]
    pendientes = avance["pendientes"]
    porcentaje = avance["porcentaje"]
    errores_catalogo = avance["errores"]

    st.subheader("📊 Avance del catálogo")

    col_completos, col_pendientes, col_total = (
        st.columns(3)
    )

    with col_completos:
        st.metric(
            "Productos completos",
            completos
        )

    with col_pendientes:
        st.metric(
            "Productos pendientes",
            pendientes
        )

    with col_total:
        st.metric(
            "Avance",
            f"{porcentaje:.1f}%"
        )

    st.progress(
        porcentaje / 100
    )

    st.caption(
        f"{completos} de {total} productos "
        "cumplen las validaciones básicas "
        "de campos obligatorios."
    )

    if pendientes == 0 and total > 0:
        st.success(
            "✅ El catálogo tiene el 100% "
            "de los campos obligatorios completos."
        )

        st.caption(
            "Este indicador no garantiza "
            "la aceptación del archivo por TUU."
        )

    elif pendientes > 0:
        st.warning(
            f"⚠️ Hay {pendientes} productos "
            "con información pendiente. "
            "Puedes descargarlos y continuar "
            "completándolos después."
        )

        with st.expander(
            "Ver productos que necesitan corrección",
            expanded=False
        ):
            st.dataframe(
                pd.DataFrame(errores_catalogo),
                hide_index=True,
                width="stretch",
                height=350
            )

    else:
        st.info(
            "El catálogo está vacío. "
            "Puedes agregar productos."
        )

    st.divider()

    st.subheader("📥 Descargar catálogo")

    nombre_sugerido = (
        ruta_trabajo.stem + "_editado.xlsx"
    )

    nombre_descarga = st.text_input(
        "Nombre del archivo",
        value=nombre_sugerido
    )

    if not nombre_descarga.lower().endswith(
        ".xlsx"
    ):
        nombre_descarga += ".xlsx"

    if ruta_trabajo.exists():
        st.download_button(
            "📥 Descargar catálogo actualizado",
            data=ruta_trabajo.read_bytes(),
            file_name=Path(nombre_descarga).name,
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            type="primary",
            use_container_width=True
        )

        st.caption(
            "La descarga está siempre disponible, "
            "aunque existan productos pendientes. "
            "El Excel original permanece intacto."
        )
