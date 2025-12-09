import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO 

# --- 1. PARÁMETROS DE AUDITORÍA (REGLAS DE NEGOCIO LQF) ---

# 🔴 LISTA DE CÓDIGOS CONTROLADOS (MÁXIMO 5% DE DESCUENTO)
codigos_controlados = [
    '3000113', '3000114', '3000080', '3000082', '3000083', '3000084', '3000085',
    '3000098', '3001265', '3001266', '3001267', '3001894', '3001896', '3002906',
    '3003648', '3004041', '3003870', '3004072', '5000002', '3004071', '3003953',
    '3003955', '3003952', '3004074', '3004073', '3003773', '3003775', '3004756'
]

# Topes de Descuento y Reglas de Negocio
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


# --- 2. FUNCIÓN PRINCIPAL DE AUDITORÍA (CON LIMPIEZA DE COLUMNAS) ---
@st.cache_data
def ejecutar_auditoria(df_ventas, df_precios):
    
    # 1. LIMPIEZA AUTOMÁTICA DE ENCABEZADOS Y NORMALIZACIÓN DE COLUMNAS DE VENTA
    df_ventas.columns = df_ventas.columns.str.strip()
    column_mapping = {
        # Mapeo de columnas de Ventas (Reporte de Facturación)
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
    # Normalizar y limpiar la tabla de precios
    df_precios.columns = df_precios.columns.str.strip()
    
    # Renombrar columnas específicas del listado de precios
    price_column_mapping = {
        'Codigo': 'Codigo', 
        'Precio de Factura con Descuento': 'Precio_Farmacia_Target', 
        'Precio Intercompany': 'Precio_Intercompany_Target'
    }
    df_precios = df_precios.rename(columns=price_column_mapping)
    
    # Seleccionar solo las columnas necesarias y asegurar que 'Codigo' sea string
    cols_a_unir = ['Codigo', 'Precio_Farmacia_Target', 'Precio_Intercompany_Target']
    df_precios = df_precios[cols_a_unir]
    df_precios['Codigo'] = df_precios['Codigo'].astype(str)
    
    # Merge de las dos tablas.
    df_audit = pd.merge(df_audit, df_precios, on='Codigo', how='left')
    
    # Rellenar con 0 para evitar errores en cálculos
    df_audit['Precio_Farmacia_Target'] = pd.to_numeric(df_audit['Precio_Farmacia_Target'], errors='coerce').fillna(0)
    df_audit['Precio_Intercompany_Target'] = pd.to_numeric(df_audit['Precio_Intercompany_Target'], errors='coerce').fillna(0)
    
    # Lógica para seleccionar el precio objetivo correcto por línea
    df_audit['Precio_Objetivo'] = np.where(
        (df_audit['Solicitante'] == CLIENTE_200046) | (df_audit['Solicitante'] == CLIENTE_200173),
        df_audit['Precio_Intercompany_Target'],
        df_audit['Precio_Farmacia_Target']
    )
    
    # Calcular el precio neto por unidad en la factura
    df_audit['Precio_Unitario_Neto_Factura'] = pd.to_numeric(df_audit['Valor neto'], errors='coerce') / pd.to_numeric(df_audit['Cant'], errors='coerce')
    
    # Calcular desviación respecto al precio objetivo (Target)
    df_audit['Desvío_Precio_Lista'] = np.where(
        (df_audit['Precio_Objetivo'] > 0) & (df_audit['Precio_Unitario_Neto_Factura'].notna()), 
        ((df_audit['Precio_Unitario_Neto_Factura'] / df_audit['Precio_Objetivo']) - 1) * 100, 
        np.nan 
    )

    # 4. Lógica de Prioridad de Descuentos (np.select)
    condiciones = [
        # 1. Empleados/Médicos con desvío
        ((df_audit['Zona de Venta'] == 'EMPLEADOS LQF') & (df_audit['Almacen'] != ALMACEN_EMPLEADOS_PERMITIDO) & (df_audit['% Desc'] > DESC_MAX_EMPLEADOS)) | \
        ((df_audit['Zona de Venta'] == 'MEDICOS PARTICULARES') & (df_audit['% Desc'] > DESC_MAX_EMPLEADOS)),
        # 2. Alerta por Precio Objetivo bajo (por debajo del -2% de tolerancia)
        (df_audit['Desvío_Precio_Lista'] < -MAX_PRECIO_DESVIACION) & (df_audit['Desvío_Precio_Lista'].notna()),
        # 3. Controlados
        (df_audit['Codigo'].isin(codigos_controlados)) & (df_audit['% Desc'] > DESC_MAX_CONTROLADOS),
        # 4. Intercompany 200046
        (df_audit['Solicitante'] == CLIENTE_200046) & (df_audit['% Desc'] > DESC_INTERCOMPANY_200046),
        # 5. Intercompany 200173
        (df_audit['Solicitante'] == CLIENTE_200173) & (df_audit['% Desc'] > DESC_INTERCOMPANY_200173), 
        # 6. Nutricia/Bebelac
        (df_audit['Jerarquia'].isin(marcas_6_porciento)) & (df_audit['% Desc'] > DESC_MAX_NUTRICIA_BEBELAC),
        # 7. General
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


    df_audit['Alerta_Descuento'] = np.select(condiciones, etiquetas_alerta, default='OK')
    desvios_encontrados = df_audit[df_audit['Alerta_Descuento'] != 'OK']
    
    return desvios_encontrados, df_audit


# --- FUNCIÓN DE EXPORTACIÓN A EXCEL (XLSX) ---
def to_excel(df):
    """
    Convierte un DataFrame de pandas a un archivo Excel (XLSX) en memoria
    para usarlo con st.download_button.
    """
    output = BytesIO()
    # Usamos pd.ExcelWriter para generar el archivo XLSX
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Reporte Auditoria')
    
    # Mover el puntero del buffer al inicio y leer todos los bytes generados
    output.seek(0)
    return output.read() 


# --- INTERFAZ STREAMLIT (EL DASHBOARD) ---

st.set_page_config(page_title="Auditoría Continua de Precios LQF", layout="wide")
st.title("🛡️ Dashboard de Auditoría de Desviaciones de Precios - LQF")

# --- CARGA DE ARCHIVOS EN LA BARRA LATERAL ---
with st.sidebar:
    st.header("⚙️ Carga de Reporte Único")
    
    # ÚNICO UPLOADER DE ARCHIVO XLSX
    uploaded_file = st.file_uploader(
        "1. Subir Archivo Único de Auditoría (.xlsx)", 
        type=['xlsx'], 
        key="auditoria_file",
        help="El archivo Excel debe contener dos hojas nombradas exactamente: 'Facturacion' y 'Listado de Precios'."
    )
    
    st.markdown("---")
    st.info("Utilice los filtros del cuerpo principal para ajustar el alcance de la auditoría.")

# --- LÓGICA DE PROCESAMIENTO Y DASHBOARD ---
if uploaded_file is not None:
    
    # 1. INTENTO DE LECTURA DE HOJAS
    try:
        # Se leen las dos hojas del mismo archivo subido
        df_ventas = pd.read_excel(uploaded_file, sheet_name='Facturacion')
        df_precios = pd.read_excel(uploaded_file, sheet_name='Listado de Precios')
        comparacion_de_precios_activa = True

    except ValueError as e:
        # Error si no encuentra alguna de las hojas
        st.error(f"Error al leer el archivo. Asegúrese de que el archivo Excel contenga dos hojas llamadas exactamente **'Facturacion'** y **'Listado de Precios'**.")
        st.stop()
        
    except Exception as e:
        st.error(f"Ocurrió un error inesperado al procesar el archivo: {e}")
        st.warning("Verifique la estructura de sus hojas de cálculo y que esté subiendo un archivo Excel válido.")
        st.stop()


    # 2. INTERFAZ DE FILTROS 
    st.subheader("Opciones de Análisis Rápido")
    
    col_filtro1, col_filtro2, col_filtro3, col_espacio = st.columns([1.5, 1.5, 1.5, 3])
    
    with col_filtro1:
        excluir_empleados = st.checkbox(
            'Excluir Empleados/Médicos', 
            value=True, 
            help='Excluye ventas con Zona de Venta: EMPLEADOS LQF y MEDICOS PARTICULARES.'
        )

    with col_filtro2:
        excluir_1012 = st.checkbox(
            'Excluir Almacén 1012', 
            value=True, 
            help='Excluye ventas provenientes del Almacén 1012 (Ofertas).'
        )

    with col_filtro3:
        ver_solo_controlados = st.checkbox(
            'Ver solo Materiales Controlados', 
            value=False, 
            help='Limita la auditoría solo a los códigos que están en la lista de control.'
        )
        
    st.markdown("---") 
    
    # 3. APLICACIÓN DE FILTROS Y EJECUCIÓN DE AUDITORÍA
    try:
        df_filtrado = df_ventas.copy()
        
        # Asegurar que las columnas tengan el formato correcto para los filtros antes de aplicar la auditoria
        df_filtrado['Almacen'] = pd.to_numeric(df_filtrado['Almacen'], errors='coerce', downcast='integer')
        df_filtrado['Zona de Venta'] = df_filtrado['Zona de Venta'].astype(str)
        df_filtrado['Codigo'] = df_filtrado['Codigo'].astype(str) 

        
        if excluir_empleados:
            df_filtrado = df_filtrado[~df_filtrado['Zona de Venta'].isin(ZONAS_EMPLEADOS)]

        if excluir_1012:
            df_filtrado = df_filtrado[df_filtrado['Almacen'] != ALMACEN_OFERTAS]
            
        if ver_solo_controlados:
            df_filtrado = df_filtrado[df_filtrado['Codigo'].astype(str).isin(codigos_controlados)]


        if df_filtrado.empty:
            st.warning("El archivo cargado no contiene transacciones después de aplicar los filtros seleccionados. Intente destildar alguna opción.")
            st.stop()
            
        # Ejecutar auditoría sobre el DataFrame filtrado (pasando df_precios)
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
            
            # Display de KPIs
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Transacciones Auditadas", f"{total_transacciones:,}")
            col2.metric("Transacciones con Desvío", f"{transacciones_desviadas:,}", delta=f"{transacciones_desviadas} líneas de riesgo")
            col3.metric("Nivel de Cumplimiento", f"{porcentaje_cumplimiento:.2f}%", delta=f"{(100 - porcentaje_cumplimiento):.2f}% de Incumplimiento", delta_color="inverse")
            col4.metric("Valor Neto de Desvíos (Gs.)", f"Gs. {valor_neto_desviado:,.0f}")
            
            st.markdown("---") 
            
            if not desvios.empty:
                st.info(f"Se encontraron **{transacciones_desviadas:,}** transacciones con desvío. Revise la pestaña 'Análisis Detallado de Riesgo'.")
            else:
                st.subheader("✅ ¡CUMPLIMIENTO TOTAL!")
                st.info("No se encontraron desviaciones en este reporte según las reglas definidas.")

        with tab2:
            if not desvios.empty:
                st.subheader("Gráfico de Riesgo: Distribución de Alertas por Tipo")
                
                # Gráfico de Barras
                alerta_counts = desvios['Alerta_Descuento'].value_counts().reset_index()
                alerta_counts.columns = ['Tipo de Alerta', 'Cantidad de Desvíos']
                alerta_counts = alerta_counts.set_index('Tipo de Alerta')
                st.bar_chart(alerta_counts, use_container_width=True, color='#f03c3c') 
                
                st.markdown("---")
                
                # DETALLE DE LA TABLA DE AUDITORÍA (Solo desvíos)
                st.subheader("Tabla Detallada de las Desviaciones")
                
                # Columnas base para la auditoría
                columnas_auditoria = ['Fecha factura', 'Almacen', 'Nombre 1', 'Codigo', 'Material', 'Jerarquia', '% Desc', 'Valor neto', 'Alerta_Descuento']
                
                # Incluir las nuevas columnas de precio (siempre activas en este flujo)
                columnas_auditoria.insert(8, 'Precio_Objetivo') 
                columnas_auditoria.insert(9, 'Desvío_Precio_Lista') 
                columnas_auditoria.insert(10, 'Precio_Unitario_Neto_Factura') 
                     
                st.dataframe(desvios[columnas_auditoria], use_container_width=True)
                
                # Opción para descargar solo los desvíos (XLSX)
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

            # Columnas seleccionadas para el listado completo
            columnas_completas = ['Fecha factura', 'Almacen', 'Nombre 1', 'Codigo', 'Material', 'Jerarquia', 'Cant', '% Desc', 'Valor neto', 'Alerta_Descuento']
            # Incluir las nuevas columnas de precio
            columnas_completas.insert(9, 'Precio_Objetivo')
            columnas_completas.insert(10, 'Desvío_Precio_Lista')
            columnas_completas.insert(11, 'Precio_Unitario_Neto_Factura')
            
            # Display del DataFrame completo
            st.dataframe(df_completo[columnas_completas], use_container_width=True)

            # Opción para descargar el archivo completo con la columna de alerta (XLSX)
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
            st.info(f"Se auditaron {total_transacciones:,} líneas contra el Precio Objetivo de la Lista. La tolerancia de desvío es de {MAX_PRECIO_DESVIACION}%.")

            # Filtrar solo donde la comparación fue posible y hay un desvío calculado
            df_comparativo = df_completo[df_completo['Desvío_Precio_Lista'].notna()].copy()
                
            # Dar formato a las columnas numéricas para visualización
            df_comparativo['Precio Objetivo (Gs.)'] = df_comparativo['Precio_Objetivo'].apply(lambda x: f"Gs. {x:,.0f}")
            df_comparativo['Precio Facturado (Gs.)'] = df_comparativo['Precio_Unitario_Neto_Factura'].apply(lambda x: f"Gs. {x:,.0f}")
            df_comparativo['Desvío (%)'] = df_comparativo['Desvío_Precio_Lista'].apply(lambda x: f"{x:,.2f}%")
                
            # Seleccionar las columnas para la tabla de comparación
            columnas_visual_comparativo = [
                'Codigo', 
                'Nombre 1', 
                'Precio Objetivo (Gs.)', 
                'Precio Facturado (Gs.)', 
                'Desvío (%)', 
                'Alerta_Descuento'
            ]
                
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

            # --- Lógica de Descarga Optimizada para XLSX ---
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
        # Se detiene si hay un error en la ejecución de la auditoría o filtros
        st.error(f"Ocurrió un error al procesar los datos después de cargarlos. Error: {e}")
        st.warning("Verifique la estructura de las columnas en sus hojas de cálculo.")
