import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO 

# Inicializar st.session_state para almacenar el archivo después de presionar "Procesar"
if 'file_data' not in st.session_state:
    st.session_state['file_data'] = None

# --- 1. CONFIGURACIÓN DE PÁGINA Y PARÁMETROS ---
codigos_controlados = [
    '3000113', '3000114', '3000080', '3000082', '3000083', '3000084', '3000085',
    '3000098', '3001265', '3001266', '3001267', '3001894', '3001896', '3002906',
    '3003648', '3004041', '3003870', '3004072', '5000002', '3004071', '3003953',
    '3003955', '3003952', '3004074', '3004073', '3003773', '3003775', '3004756'
]

DESC_MAX_CONTROLADOS = 5.0
DESC_MAX_EMPLEADOS = 0.0
DESC_MAX_NUTRICIA_BEBELAC = 6.0
DESC_MAX_GENERAL = 7.0
MAX_PRECIO_DESVIACION = 2.0 
DESC_INTERCOMPANY_200046 = 11.0 
DESC_INTERCOMPANY_200173 = 10.0 
CLIENTE_200046 = '200046'
CLIENTE_200173 = '200173'
ALMACEN_EMPLEADOS_PERMITIDO = 1041
ALMACEN_OFERTAS = 1012
marcas_6_porciento = ['NUTRICIA', 'BEBELAC']
ZONAS_EMPLEADOS = ['EMPLEADOS LQF', 'MEDICOS PARTICULARES']


# --- 2. FUNCIÓN PRINCIPAL DE AUDITORÍA (PERMANECE SIN CAMBIOS) ---
@st.cache_data
def ejecutar_auditoria(df_ventas, df_precios):
    
    # 1. LIMPIEZA AUTOMÁTICA DE ENCABEZADOS Y NORMALIZACIÓN DE COLUMNAS DE VENTA
    df_ventas.columns = df_ventas.columns.str.strip()
    column_mapping = {
        'Fecha factura': 'Fecha factura', 'Almacen': 'Almacen', 'Tipo Venta': 'Tipo Venta',
        'Zona de Venta': 'Zona de Venta', 'Solicitante': 'Solicitante', 'Nombre 1': 'Nombre 1',
        'Codigo': 'Codigo', 'Material': 'Material', 'Jerarquia': 'Jerarquia',
        '% Desc': '% Desc', 'Valor neto': 'Valor neto', 'Cant': 'Cant',
        'Descuento %': '% Desc', 'codigo': 'Codigo', 'jerarquia': 'Jerarquia', 
        'Valor Neto': 'Valor neto', 'VALOR NETO': 'Valor neto'
    }
    df_audit = df_ventas.rename(columns=column_mapping)
    
    # 2. Limpieza y Normalización de Datos de Venta
    df_audit['% Desc'] = pd.to_numeric(df_audit['% Desc'], errors='coerce')
    df_audit['Almacen'] = pd.to_numeric(df_audit['Almacen'], errors='coerce', downcast='integer')
    df_audit['Solicitante'] = df_audit['Solicitante'].astype(str)
    df_audit['Codigo'] = df_audit['Codigo'].astype(str)
    
    
    # 3. Auditoría por Precio de Lista (Listado de Precios)
    df_precios.columns = df_precios.columns.str.strip()
    price_column_mapping = {
        'Codigo': 'Codigo', 
        'IVA': 'IVA_Lista', 
        'Precio de Factura con Descuento': 'Precio_Farmacia_Target', 
        'Precio Intercompany': 'Precio_Intercompany_Target'
    }
    df_precios = df_precios.rename(columns=price_column_mapping)
    
    cols_a_unir = ['Codigo', 'IVA_Lista', 'Precio_Farmacia_Target', 'Precio_Intercompany_Target'] 
    df_precios = df_precios[cols_a_unir]
    df_precios['Codigo'] = df_precios['Codigo'].astype(str)
    df_precios['IVA_Lista'] = pd.to_numeric(df_precios['IVA_Lista'], errors='coerce').fillna(0) 
    
    df_audit = pd.merge(df_audit, df_precios, on='Codigo', how='left')
    
    # --- AJUSTE CRÍTICO: QUITAR EL IVA DEL PRECIO OBJETIVO (PARA COMPARAR CON NETO) ---
    df_audit['Factor_IVA'] = 1 + df_audit['IVA_Lista']
    df_audit['Factor_IVA'] = np.where(df_audit['Factor_IVA'] <= 1, np.nan, df_audit['Factor_IVA']) 

    df_audit['Precio_Farmacia_Target'] = pd.to_numeric(df_audit['Precio_Farmacia_Target'], errors='coerce').fillna(0)
    df_audit['Precio_Intercompany_Target'] = pd.to_numeric(df_audit['Precio_Intercompany_Target'], errors='coerce').fillna(0)
    
    df_audit['Precio_Farmacia_Target_SIN_IVA'] = np.where(
        df_audit['Factor_IVA'].notna(), 
        df_audit['Precio_Farmacia_Target'] / df_audit['Factor_IVA'],
        df_audit['Precio_Farmacia_Target'] 
    )
    
    df_audit['Precio_Intercompany_Target_SIN_IVA'] = np.where(
        df_audit['Factor_IVA'].notna(), 
        df_audit['Precio_Intercompany_Target'] / df_audit['Factor_IVA'],
        df_audit['Precio_Intercompany_Target']
    )
    
    df_audit['Precio_Farmacia_Target_SIN_IVA'] = df_audit['Precio_Farmacia_Target_SIN_IVA'].fillna(0)
    df_audit['Precio_Intercompany_Target_SIN_IVA'] = df_audit['Precio_Intercompany_Target_SIN_IVA'].fillna(0)
    
    df_audit['Precio_Objetivo'] = np.where(
        (df_audit['Solicitante'] == CLIENTE_200046) | (df_audit['Solicitante'] == CLIENTE_200173),
        df_audit['Precio_Intercompany_Target_SIN_IVA'],
        df_audit['Precio_Farmacia_Target_SIN_IVA']
    )
    
    df_audit['Precio_Unitario_Neto_Factura'] = pd.to_numeric(df_audit['Valor neto'], errors='coerce') / pd.to_numeric(df_audit['Cant'], errors='coerce')
    
    df_audit['Desvío_Precio_Lista'] = np.where(
        (df_audit['Precio_Objetivo'] > 0) & (df_audit['Precio_Unitario_Neto_Factura'].notna()), 
        ((df_audit['Precio_Unitario_Neto_Factura'] / df_audit['Precio_Objetivo']) - 1) * 100, 
        np.nan 
    )

    # 4. Lógica de Prioridad de Descuentos (np.select)
    condiciones = [
        ((df_audit['Zona de Venta'] == 'EMPLEADOS LQF') & (df_audit['Almacen'] != ALMACEN_EMPLEADOS_PERMITIDO) & (df_audit['% Desc'] > DESC_MAX_EMPLEADOS)) | \
        ((df_audit['Zona de Venta'] == 'MEDICOS PARTICULARES') & (df_audit['% Desc'] > DESC_MAX_EMPLEADOS)),
        (df_audit['Desvío_Precio_Lista'] < -MAX_PRECIO_DESVIACION) & (df_audit['Desvío_Precio_Lista'].notna()),
        (df_audit['Codigo'].isin(codigos_controlados)) & (df_audit['% Desc'] > DESC_MAX_CONTROLADOS),
        (df_audit['Solicitante'] == CLIENTE_200046) & (df_audit['% Desc'] > DESC_INTERCOMPANY_200046),
        (df_audit['Solicitante'] == CLIENTE_200173) & (df_audit['% Desc'] > DESC_INTERCOMPANY_200173), 
        (df_audit['Jerarquia'].isin(marcas_6_porciento)) & (df_audit['% Desc'] > DESC_MAX_NUTRICIA_BEBELAC), 
        (df_audit['% Desc'] > DESC_MAX_GENERAL)
    ]
    etiquetas_alerta = [
        '❌ Ilegal (Empleado/Médico)', 
        f'⛔ Precio Facturado bajo (>{MAX_PRECIO_DESVIACION}%)',
        '⚠️ Controlado (>5%) Excedido',
        '⚠️ Intercompany 200046 (>11%) Excedido', 
        '⚠️ Intercompany 200173 (>10%) Excedido', 
        '⚠️ Marca Nutricion (>6%) Excedido', 
        '⚠️ General (>7%) Excedido'
    ]

    df_audit['Alerta_Descuento'] = np.select(condiciones, etiquetas_alerta, default='✅ OK')
    desvios_encontrados = df_audit[df_audit['Alerta_Descuento'] != '✅ OK']
    
    return desvios_encontrados, df_audit


# --- FUNCIÓN DE EXPORTACIÓN A EXCEL (XLSX) ---
def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Reporte Auditoria')
    output.seek(0)
    return output.read() 


# --- INTERFAZ STREAMLIT (EL DASHBOARD) ---

st.set_page_config(page_title="Auditoría Continua de Precios LQF", layout="wide")


# --- INYECCIÓN DE CSS PARA ESTILO Y POSICIONAMIENTO SUPERIOR Y CENTRADO ---
st.markdown("""
<style>
/* Aumenta el padding-top del contenedor principal para dar más espacio arriba */
.block-container {
    padding-top: 2rem; 
    padding-bottom: 0rem;
    padding-left: 1rem;
    padding-right: 1rem;
}

/* Estilo para el Título Principal (h1) */
h1 {
    font-size: 1.8em !important; 
    color: #4A148C; 
    font-family: 'Segoe UI Black', 'Arial Black', sans-serif; 
    text-align: center; /* CENTRADO DEL TÍTULO */
    /* MARGEN AUMENTADO A 4rem para evitar la superposición con el header fijo de Streamlit */
    margin-top: 4rem; 
    margin-bottom: 0px; 
    padding-top: 0px;
}

/* Estilo para los Subtítulos de Secciones (h2/h3) */
h2, h3 {
    font-size: 1.5em !important; 
    color: #00897B; 
    border-bottom: 1px solid #E0F2F1; 
    padding-bottom: 5px;
    margin-top: 20px;
}

/* Estilo para todo el texto de la aplicación (cuerpo) */
.stApp {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    font-size: 1.05em; 
}
</style>
""", unsafe_allow_html=True)
# ----------------------------------------------------------------

# TÍTULO PRINCIPAL
st.title("Tablero de control de facturación")

# --- LÓGICA DE PANTALLA CONDICIONAL ---
if st.session_state['file_data'] is None:
    # ----------------------------------------------------
    # ESTADO 1: PANTALLA DE CARGA MINIMALISTA
    # ----------------------------------------------------
    st.markdown("---")
    
    # Usar columnas para centrar el formulario de carga
    col_l, col_c, col_r = st.columns([1, 2, 1])
    
    with col_c:
        # Usamos un formulario para asegurar que la acción se dispare solo con el botón "Procesar"
        with st.form("upload_form", clear_on_submit=False):
            # Uploader (sin texto extra)
            uploaded_file_temp = st.file_uploader(
                "**Subir Archivo Único de Auditoría (.xlsx)**", 
                type=['xlsx'], 
                key="auditoria_file_temp",
                help="El archivo Excel debe contener dos hojas nombradas exactamente: 'Facturacion' y 'Listado de Precios'."
            )
            # Botón de Procesar
            submitted = st.form_submit_button("➡️ Procesar Datos y Abrir Tablero")

        if submitted:
            if uploaded_file_temp is not None:
                # Si hay archivo y se presiona, lo guardamos en session_state y recargamos
                st.session_state['file_data'] = uploaded_file_temp
                st.rerun() 
            else:
                st.error("Por favor, suba un archivo antes de presionar 'Procesar'.")

else:
    # ----------------------------------------------------
    # ESTADO 2: DASHBOARD ACTIVO (ARCHIVO GUARDADO EN SESSION STATE)
    # ----------------------------------------------------
    uploaded_file = st.session_state['file_data']
    
    # 1. INTENTO DE LECTURA DE HOJAS
    try:
        df_ventas = pd.read_excel(uploaded_file, sheet_name='Facturacion')
        df_precios = pd.read_excel(uploaded_file, sheet_name='Listado de Precios')
    except ValueError as e:
        st.error(f"Error al leer el archivo. Asegúrese de que el archivo Excel contenga dos hojas llamadas exactamente **'Facturacion'** y **'Listado de Precios'**.")
        # Limpiamos el estado para que vuelva a la pantalla de carga
        st.session_state['file_data'] = None
        st.stop()
    except Exception as e:
        st.error(f"Ocurrió un error inesperado al procesar el archivo: {e}")
        st.warning("Verifique la estructura de sus hojas de cálculo y que esté subiendo un archivo Excel válido.")
        st.session_state['file_data'] = None
        st.stop()


    # 2. INTERFAZ DE FILTROS 
    st.subheader("Opciones de Análisis Rápido")
    
    # --- FILTROS DE EXCLUSIÓN ---
    st.markdown("### 🚫 1. Filtros de Exclusión de Canales")
    col_excluir1, col_excluir2, col_espacio1 = st.columns([1.5, 1.5, 4])
    
    with col_excluir1:
        excluir_empleados = st.checkbox(
            'Excluir Canales de Empleados/Médicos', 
            value=True, 
            key='check_excluir_empleados',
            help='Excluye ventas con Zona de Venta: EMPLEADOS LQF y MEDICOS PARTICULARES.'
        )

    with col_excluir2:
        excluir_1012 = st.checkbox(
            'Excluir Almacén de Ofertas (1012)', 
            value=True, 
            key='check_excluir_1012',
            help='Excluye ventas provenientes del Almacén 1012 (Ofertas).'
        )

    # --- FILTROS DE INCLUSIÓN ---
    st.markdown("### ✨ 2. Filtros de Materiales")
    col_incluir1, col_espacio2 = st.columns([3, 4])

    with col_incluir1:
        ver_solo_controlados = st.checkbox(
            'Ver **SOLO** Materiales Controlados', 
            value=False, 
            key='check_solo_controlados',
            help='Limita la auditoría solo a los códigos que están en la lista de control (Ignora todos los demás).'
        )
        
    st.markdown("---") 
    
    # 3. APLICACIÓN DE FILTROS Y EJECUCIÓN DE AUDITORÍA
    try:
        df_filtrado = df_ventas.copy()
        
        df_filtrado['Almacen'] = pd.to_numeric(df_filtrado['Almacen'], errors='coerce', downcast='integer')
        df_filtrado['Zona de Venta'] = df_filtrado['Zona de Venta'].astype(str)
        df_filtrado['Codigo'] = df_filtrado['Codigo'].astype(str) 

        
        # Lógica de Exclusión
        if excluir_empleados:
            df_filtrado = df_filtrado[~df_filtrado['Zona de Venta'].isin(ZONAS_EMPLEADOS)]

        if excluir_1012:
            df_filtrado = df_filtrado[df_filtrado['Almacen'] != ALMACEN_OFERTAS]
            
        # Lógica de Inclusión (Ver solo)
        if ver_solo_controlados:
            df_filtrado = df_filtrado[df_filtrado['Codigo'].astype(str).isin(codigos_controlados)]


        if df_filtrado.empty:
            st.warning("El archivo cargado no contiene transacciones después de aplicar los filtros seleccionados. Intente destildar alguna opción.")
            st.stop()
            
        # Ejecutar auditoría sobre el DataFrame filtrado
        desvios, df_completo = ejecutar_auditoria(df_filtrado, df_precios)
        
        # CÁLCULO DE KPIs (Métricas)
        total_transacciones = len(df_completo)
        transacciones_desviadas = len(desvios)
        porcentaje_cumplimiento = (1 - (transacciones_desviadas / total_transacciones)) * 100 if total_transacciones > 0 else 0
        valor_neto_desviado = pd.to_numeric(desvios['Valor neto'], errors='coerce').sum()
        
        # --- Implementación de 4 Pestañas (Tabs) ---
        tab1, tab2, tab3, tab4 = st.tabs(["📊 Resumen Ejecutivo", "⚠️ Análisis Detallado de Riesgo", "📝 Listado Completo", "💲 Comparativo de Precios"])

        with tab1:
            st.header("Métricas Clave de Cumplimiento")
            
            # Display de KPIs con formato y color
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Transacciones Auditadas", f"{total_transacciones:,}")
            col2.metric("Transacciones con Desvío", f"{transacciones_desviadas:,}", delta=f"{transacciones_desviadas} líneas de riesgo", delta_color="inverse")
            col3.metric("Nivel de Cumplimiento", f"{porcentaje_cumplimiento:.2f}%", delta=f"{(100 - porcentaje_cumplimiento):.2f}% de Incumplimiento", delta_color="inverse")
            col4.metric("Valor Neto de Desvíos (Gs.)", f"Gs. {valor_neto_desviado:,.0f}")
            
            st.markdown("---") 
            
            if not desvios.empty:
                st.error(f"Se encontraron **{transacciones_desviadas:,}** transacciones con desvío. Revise la pestaña 'Análisis Detallado de Riesgo'.")
            else:
                st.subheader("✅ ¡CUMPLIMIENTO TOTAL!")
                st.success("No se encontraron desviaciones en este reporte según las reglas definidas.")

        with tab2:
            if not desvios.empty:
                st.subheader("Gráfico de Riesgo: Distribución de Alertas por Tipo")
                
                alerta_counts = desvios['Alerta_Descuento'].value_counts().reset_index()
                alerta_counts.columns = ['Tipo de Alerta', 'Cantidad de Desvíos']
                alerta_counts = alerta_counts.set_index('Tipo de Alerta')
                st.bar_chart(alerta_counts, use_container_width=True, color='#f03c3c') 
                
                st.markdown("---")
                
                st.subheader("Tabla Detallada de las Desviaciones")
                
                columnas_auditoria = ['Fecha factura', 'Almacen', 'Nombre 1', 'Codigo', 'Material', 'Jerarquia', '% Desc', 'Valor neto', 'Alerta_Descuento']
                columnas_auditoria.insert(8, 'Precio_Objetivo') 
                columnas_auditoria.insert(9, 'Desvío_Precio_Lista') 
                columnas_auditoria.insert(10, 'Precio_Unitario_Neto_Factura') 
                     
                st.dataframe(
                    desvios[columnas_auditoria].style.format({
                        '% Desc': '{:.2f}%',
                        'Valor neto': 'Gs. {:,.0f}',
                        'Precio_Objetivo': 'Gs. {:,.2f}',
                        'Desvío_Precio_Lista': '{:.2f}%',
                        'Precio_Unitario_Neto_Factura': 'Gs. {:,.2f}'
                    }), 
                    use_container_width=True
                )
                
                df_export_desvios = desvios[columnas_auditoria]
                xlsx_data_desvios = to_excel(df_export_desvios)
                
                st.download_button(
                    label="Descargar Alertas en XLSX (Excel)", 
                    data=xlsx_data_desvios, 
                    file_name='Reporte_Desviaciones_LQF.xlsx', 
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    key="descarga_alertas" 
                )
                
            else:
                st.info("No hay desvíos que analizar en este reporte.")

        with tab3:
            st.subheader("Listado de Todas las Transacciones Verificadas")
            st.info("Esta tabla muestra todas las líneas del archivo cargado con el resultado de la auditoría (OK o Alerta), luego de aplicar los filtros.")

            columnas_completas = ['Fecha factura', 'Almacen', 'Nombre 1', 'Codigo', 'Material', 'Jerarquia', 'Cant', '% Desc', 'Valor neto', 'Alerta_Descuento']
            columnas_completas.insert(9, 'Precio_Objetivo')
            columnas_completas.insert(10, 'Desvío_Precio_Lista')
            columnas_completas.insert(11, 'Precio_Unitario_Neto_Factura')
            
            st.dataframe(
                 df_completo[columnas_completas].style.format({
                    '% Desc': '{:.2f}%',
                    'Valor neto': 'Gs. {:,.0f}',
                    'Precio_Objetivo': 'Gs. {:,.2f}',
                    'Desvío_Precio_Lista': '{:.2f}%',
                    'Precio_Unitario_Neto_Factura': 'Gs. {:,.2f}'
                }),
                use_container_width=True
            )

            df_export_completo = df_completo[columnas_completas]
            xlsx_data_completo = to_excel(df_export_completo)

            st.download_button(
                label="Descargar Listado Completo Auditado en XLSX (Excel)", 
                data=xlsx_data_completo, 
                file_name='Reporte_Completo_Auditado_LQF.xlsx', 
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                key="descarga_completa" 
            )
            
        with tab4:
            st.header("Análisis de Desviación de Precios vs. Objetivo")
            st.info(f"Se auditaron **{total_transacciones:,}** líneas contra el Precio Objetivo de la Lista SIN IVA. La tolerancia de desvío es de {MAX_PRECIO_DESVIACION}%.")

            df_comparativo = df_completo[df_completo['Desvío_Precio_Lista'].notna()].copy()
                
            df_comparativo['Precio Objetivo SIN IVA (Gs.)'] = df_comparativo['Precio_Objetivo'].apply(lambda x: f"Gs. {x:,.0f}")
            df_comparativo['Precio Facturado Neto (Gs.)'] = df_comparativo['Precio_Unitario_Neto_Factura'].apply(lambda x: f"Gs. {x:,.0f}")
            df_comparativo['Desvío (%)'] = df_comparativo['Desvío_Precio_Lista'] 
                
            columnas_visual_comparativo = [
                'Codigo', 
                'Nombre 1', 
                'Precio Objetivo SIN IVA (Gs.)', 
                'Precio Facturado Neto (Gs.)', 
                'Desvío (%)', 
                'Alerta_Descuento'
            ]
                
            if not df_comparativo.empty:
                st.subheader("Visualización de Desviaciones de Precio")
                st.dataframe(
                    df_comparativo[columnas_visual_comparativo], 
                    use_container_width=True,
                    column_config={
                        "Desvío (%)": st.column_config.ProgressColumn(
                            "Desvío (%)",
                            help="Porcentaje de diferencia respecto al Precio Objetivo. Los negativos indican que se facturó a un precio inferior.",
                            format="%.2f%%",
                            min_value=-20, 
                            max_value=10, 
                            width="medium"
                        )
                    }
                )
            else:
                 st.info("No hay datos para el comparativo después de aplicar filtros.")

            columnas_csv_comparativo = [
                'Fecha factura', 'Nombre 1', 'Solicitante', 'Codigo', 'Material', 
                'Jerarquia', 'Cant', '% Desc', 'Valor neto', 
                'Precio_Objetivo', 'Precio_Unitario_Neto_Factura', 'Desvío_Precio_Lista', 
                'Alerta_Descuento'
            ]
                
            df_export_comparativo = df_completo[df_completo['Desvío_Precio_Lista'].notna()][columnas_csv_comparativo]
            xlsx_data_comparativo = to_excel(df_export_comparativo)

            st.download_button(
                label="Descargar Reporte de Comparativo de Precios en XLSX (Detallado)", 
                data=xlsx_data_comparativo, 
                file_name='Reporte_Comparativo_Precios_LQF_Detallado.xlsx', 
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                key="descarga_comparativo" 
            )

    except Exception as e:
        st.error(f"Ocurrió un error al procesar los datos después de cargarlos. Error: {e}")
        st.warning("Verifique la estructura de las columnas en sus hojas de cálculo.")
        st.session_state['file_data'] = None
