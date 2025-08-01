import pandas as pd
import duckdb
import numpy as np
from datetime import datetime
import os
import re
from typing import List, Dict, Optional, Union
from tqdm import tqdm
import logging

# Set up logging
logger = logging.getLogger(__name__)


def create_wide_dataset(
    clif_instance,
    optional_tables: Optional[List[str]] = None,
    category_filters: Optional[Dict[str, List[str]]] = None,
    sample: bool = False,
    hospitalization_ids: Optional[List[str]] = None,
    cohort_df: Optional[pd.DataFrame] = None,
    output_format: str = 'dataframe',
    save_to_data_location: bool = False,
    output_filename: Optional[str] = None,
    return_dataframe: bool = True,
    base_table_columns: Optional[Dict[str, List[str]]] = None,
    batch_size: int = 1000,
    memory_limit: Optional[str] = None,
    threads: Optional[int] = None,
    show_progress: bool = True
) -> Optional[pd.DataFrame]:
    """
    Create a wide dataset by joining multiple CLIF tables with pivoting support.
    
    Parameters:
        clif_instance: CLIF object with loaded data
        optional_tables: DEPRECATED - use category_filters to specify tables
        category_filters: Dict specifying which categories to include for each table
                         Keys are table names, values are lists of categories to filter
                         Table presence in this dict determines if it will be loaded
        sample: Boolean - if True, randomly select 20 hospitalizations
        hospitalization_ids: List of specific hospitalization IDs to filter
        cohort_df: Optional DataFrame with columns ['hospitalization_id', 'start_time', 'end_time']
                   If provided, data will be filtered to only include events within the specified
                   time windows for each hospitalization
        output_format: 'dataframe', 'csv', or 'parquet'
        save_to_data_location: Boolean - save output to data directory
        output_filename: Custom filename (default: 'wide_dataset_YYYYMMDD_HHMMSS')
        return_dataframe: Boolean - return DataFrame even when saving to file (default=True)
        base_table_columns: DEPRECATED - columns are selected automatically
        batch_size: Number of hospitalizations to process in each batch (default=1000)
        memory_limit: DuckDB memory limit (e.g., '8GB')
        threads: Number of threads for DuckDB to use
        show_progress: Show progress bars for long operations
    
    Returns:
        pd.DataFrame or None (if return_dataframe=False)
    """
    
    print("Starting wide dataset creation...")
    
    # Validate cohort_df if provided
    if cohort_df is not None:
        required_cols = ['hospitalization_id', 'start_time', 'end_time']
        missing_cols = [col for col in required_cols if col not in cohort_df.columns]
        if missing_cols:
            raise ValueError(f"cohort_df must contain columns: {required_cols}. Missing: {missing_cols}")
        
        # Ensure hospitalization_id is string type to match with other tables
        cohort_df['hospitalization_id'] = cohort_df['hospitalization_id'].astype(str)
        
        # Ensure time columns are datetime
        for time_col in ['start_time', 'end_time']:
            if not pd.api.types.is_datetime64_any_dtype(cohort_df[time_col]):
                cohort_df[time_col] = pd.to_datetime(cohort_df[time_col])
        
        print(f"Using cohort_df with time windows for {len(cohort_df)} hospitalizations")
    
    # Define tables that need pivoting vs those already wide
    PIVOT_TABLES = ['vitals', 'labs', 'medication_admin_continuous', 'patient_assessments']
    WIDE_TABLES = ['respiratory_support']
    
    # Determine which tables to load from category_filters
    if category_filters is None:
        category_filters = {}
    
    # For backward compatibility with optional_tables
    if optional_tables and not category_filters:
        print("Warning: optional_tables parameter is deprecated. Converting to category_filters format.")
        category_filters = {table: [] for table in optional_tables}
    
    tables_to_load = list(category_filters.keys())
    
    # Create DuckDB connection with optimized settings
    conn_config = {
        'preserve_insertion_order': 'false'
    }
    
    if memory_limit:
        conn_config['memory_limit'] = memory_limit
    if threads:
        conn_config['threads'] = str(threads)
    
    # Use context manager for connection
    with duckdb.connect(':memory:', config=conn_config) as conn:
        # Set additional optimization settings
        conn.execute("SET preserve_insertion_order = false")
        
        # Get hospitalization IDs to process
        hospitalization_df = clif_instance.hospitalization.df.copy()
        
        if hospitalization_ids is not None:
            print(f"Filtering to specific hospitalization IDs: {len(hospitalization_ids)} encounters")
            required_ids = hospitalization_ids
        elif cohort_df is not None:
            # Use hospitalization IDs from cohort_df
            required_ids = cohort_df['hospitalization_id'].unique().tolist()
            print(f"Using {len(required_ids)} hospitalization IDs from cohort_df")
        elif sample:
            print("Sampling 20 random hospitalizations...")
            all_ids = hospitalization_df['hospitalization_id'].unique()
            required_ids = np.random.choice(all_ids, size=min(20, len(all_ids)), replace=False).tolist()
            print(f"Selected {len(required_ids)} hospitalizations for sampling")
        else:
            required_ids = hospitalization_df['hospitalization_id'].unique().tolist()
            print(f"Processing all {len(required_ids)} hospitalizations")
        
        # Filter all base tables by required IDs immediately
        print("\nLoading and filtering base tables...")
        # Only keep required columns from hospitalization table
        hosp_required_cols = ['hospitalization_id', 'patient_id', 'age_at_admission']
        hosp_available_cols = [col for col in hosp_required_cols if col in hospitalization_df.columns]
        hospitalization_df = hospitalization_df[hosp_available_cols]
        hospitalization_df = hospitalization_df[hospitalization_df['hospitalization_id'].isin(required_ids)]
        patient_df = clif_instance.patient.df[['patient_id']].copy()
        
        # Get ADT with selected columns
        adt_df = clif_instance.adt.df.copy()
        adt_df = adt_df[adt_df['hospitalization_id'].isin(required_ids)]
        # Remove duplicate columns and _name columns
        adt_cols = [col for col in adt_df.columns if not col.endswith('_name') and col != 'patient_id']
        adt_df = adt_df[adt_cols]
        
        print(f"Base tables filtered - Hospitalization: {len(hospitalization_df)}, Patient: {len(patient_df)}, ADT: {len(adt_df)}")
        
        # Process in batches to avoid memory issues
        if batch_size > 0 and len(required_ids) > batch_size:
            print(f"Processing {len(required_ids)} hospitalizations in batches of {batch_size}")
            return _process_in_batches(
                conn, clif_instance, required_ids, patient_df, hospitalization_df, adt_df,
                tables_to_load, category_filters, PIVOT_TABLES, WIDE_TABLES,
                batch_size, show_progress, save_to_data_location, output_filename,
                output_format, return_dataframe, cohort_df
            )
        else:
            # Process all at once for small datasets
            return _process_hospitalizations(
                conn, clif_instance, required_ids, patient_df, hospitalization_df, adt_df,
                tables_to_load, category_filters, PIVOT_TABLES, WIDE_TABLES,
                show_progress, cohort_df
            )


def _find_alternative_timestamp(table_name: str, columns: List[str]) -> Optional[str]:
    """Find alternative timestamp column if the default is not found."""
    
    alternatives = {
        'labs': ['lab_collect_dttm', 'recorded_dttm', 'lab_order_dttm'],
        'vitals': ['recorded_dttm_min', 'recorded_dttm'],
    }
    
    if table_name in alternatives:
        for alt_col in alternatives[table_name]:
            if alt_col in columns:
                return alt_col
    
    return None


def _save_dataset(
    df: pd.DataFrame,
    data_dir: str,
    output_filename: Optional[str],
    output_format: str
):
    """Save the dataset to file."""
    
    if output_filename is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_filename = f'wide_dataset_{timestamp}'
    
    output_path = os.path.join(data_dir, f'{output_filename}.{output_format}')
    
    if output_format == 'csv':
        df.to_csv(output_path, index=False)
    elif output_format == 'parquet':
        df.to_parquet(output_path, index=False)
    
    print(f"Wide dataset saved to: {output_path}")


def _get_timestamp_column(table_name: str) -> Optional[str]:
    """Get the timestamp column name for each table type."""
    timestamp_mapping = {
        'vitals': 'recorded_dttm',
        'labs': 'lab_result_dttm',
        'medication_admin_continuous': 'admin_dttm',
        'patient_assessments': 'recorded_dttm',
        'respiratory_support': 'recorded_dttm'
    }
    return timestamp_mapping.get(table_name)




def convert_wide_to_hourly_optimized(
    wide_df: pd.DataFrame, 
    aggregation_config: Dict[str, List[str]],
    memory_limit: str = '4GB',
    temp_directory: Optional[str] = None,
    batch_size: Optional[int] = None
) -> pd.DataFrame:
    """
    Optimized version using DuckDB for fast hourly aggregation.
    
    Parameters:
        wide_df: Wide dataset DataFrame from create_wide_dataset()
        aggregation_config: Dict mapping aggregation methods to list of columns
        memory_limit: DuckDB memory limit (e.g., '4GB', '8GB')
        temp_directory: Directory for temporary files (default: system temp)
        batch_size: Process in batches if dataset is large (auto-determined if None)
        
    Returns:
        pd.DataFrame: Hourly aggregated wide dataset with nth_hour column
    """
    
    print("Starting optimized hourly aggregation using DuckDB...")
    print(f"Input dataset shape: {wide_df.shape}")
    print(f"Memory limit: {memory_limit}")
    
    # Validate input
    required_columns = ['event_time', 'hospitalization_id', 'day_number']
    for col in required_columns:
        if col not in wide_df.columns:
            raise ValueError(f"wide_df must contain '{col}' column")
    
    # Auto-determine batch size for very large datasets
    if batch_size is None:
        n_rows = len(wide_df)
        n_hospitalizations = wide_df['hospitalization_id'].nunique()
        
        # Use batching if dataset is very large
        if n_rows > 1_000_000 or n_hospitalizations > 10_000:
            batch_size = min(5000, n_hospitalizations // 4)
            print(f"Large dataset detected ({n_rows:,} rows, {n_hospitalizations:,} hospitalizations)")
            print(f"Will process in batches of {batch_size} hospitalizations")
        else:
            batch_size = 0  # Process all at once
    
    # Configure DuckDB connection
    config = {
        'memory_limit': memory_limit,
        'temp_directory': temp_directory or '/tmp/duckdb_temp',
        'preserve_insertion_order': 'false',
        'threads': '4'
    }
    
    # Remove None values from config
    config = {k: v for k, v in config.items() if v is not None}
    
    try:
        # Create DuckDB connection with error handling
        with duckdb.connect(':memory:', config=config) as conn:
            # Set additional optimization settings
            conn.execute("SET preserve_insertion_order = false")
            # Note: enable_progress_bar is not supported in all DuckDB versions
            
            if batch_size > 0:
                return _process_hourly_in_batches(conn, wide_df, aggregation_config, batch_size)
            else:
                return _process_hourly_single_batch(conn, wide_df, aggregation_config)
                
    except Exception as e:
        print(f"DuckDB processing failed: {str(e)}")
        raise


def _process_hourly_single_batch(
    conn: duckdb.DuckDBPyConnection,
    wide_df: pd.DataFrame,
    aggregation_config: Dict[str, List[str]]
) -> pd.DataFrame:
    """Process entire dataset in a single batch with progress tracking by aggregation type."""
    
    try:
        # Register the DataFrame
        conn.register('wide_data', wide_df)
        
        # Create base table with hourly buckets
        print("Creating hourly buckets...")
        conn.execute("""
            CREATE OR REPLACE TABLE hourly_base AS
            SELECT 
                *,
                date_trunc('hour', event_time) AS event_time_hour,
                EXTRACT(hour FROM event_time) AS hour_bucket
            FROM wide_data
        """)
        
        # Calculate nth_hour
        print("Calculating nth_hour...")
        conn.execute("""
            CREATE OR REPLACE TABLE hourly_data AS
            WITH first_events AS (
                SELECT 
                    hospitalization_id,
                    MIN(event_time_hour) AS first_event_hour
                FROM hourly_base
                GROUP BY hospitalization_id
            )
            SELECT 
                hb.*,
                CAST((EPOCH(hb.event_time_hour) - EPOCH(fe.first_event_hour)) / 3600 AS INTEGER) AS nth_hour
            FROM hourly_base hb
            JOIN first_events fe ON hb.hospitalization_id = fe.hospitalization_id
        """)
        
        # Build separate queries for each aggregation type
        agg_queries = _build_aggregation_query_duckdb(conn, aggregation_config, wide_df.columns)
        
        # Execute base query first
        print("\nProcessing aggregations by type:")
        print("- Extracting base columns...")
        base_df = conn.execute(agg_queries['base']).df()
        
        # Process each aggregation type separately
        aggregation_results = [base_df]
        
        # Define the order of operations for better user feedback
        agg_order = ['max', 'min', 'mean', 'median', 'first', 'last', 'boolean', 'one_hot_encode']
        
        for agg_type in agg_order:
            if agg_type in agg_queries and agg_type != 'base':
                print(f"- Processing {agg_type} aggregation...")
                try:
                    agg_result = conn.execute(agg_queries[agg_type]).df()
                    # Drop the group by columns from aggregation results to avoid duplicates
                    cols_to_drop = ['hospitalization_id', 'event_time_hour', 'nth_hour', 'hour_bucket']
                    agg_result = agg_result.drop(columns=cols_to_drop)
                    aggregation_results.append(agg_result)
                    print(f"  ✓ {agg_type} complete ({agg_result.shape[1]} columns)")
                except Exception as e:
                    print(f"  ✗ {agg_type} failed: {str(e)}")
        
        # Merge all results
        print("\nMerging aggregation results...")
        result_df = pd.concat(aggregation_results, axis=1)
        
        # Sort by hospitalization_id and nth_hour
        result_df = result_df.sort_values(['hospitalization_id', 'nth_hour']).reset_index(drop=True)
        
        print(f"\nHourly aggregation complete: {len(result_df)} hourly records")
        print(f"Columns in hourly dataset: {len(result_df.columns)}")
        
        return result_df
        
    except Exception as e:
        print(f"Single batch processing failed: {str(e)}")
        raise


def _process_hourly_in_batches(
    conn: duckdb.DuckDBPyConnection,
    wide_df: pd.DataFrame,
    aggregation_config: Dict[str, List[str]],
    batch_size: int
) -> pd.DataFrame:
    """Process dataset in batches to manage memory usage with progress tracking."""
    
    print(f"Processing in batches of {batch_size} hospitalizations...")
    
    # Get unique hospitalization IDs
    unique_hosp_ids = wide_df['hospitalization_id'].unique()
    n_batches = (len(unique_hosp_ids) + batch_size - 1) // batch_size
    
    batch_results = []
    
    # Use tqdm for batch-level progress
    batch_iterator = tqdm(range(0, len(unique_hosp_ids), batch_size), 
                         desc="Processing batches", 
                         total=n_batches,
                         unit="batch")
    
    for i in batch_iterator:
        batch_ids = unique_hosp_ids[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        batch_iterator.set_description(f"Processing batch {batch_num}/{n_batches}")
        
        try:
            # Filter to current batch
            batch_df = wide_df[wide_df['hospitalization_id'].isin(batch_ids)].copy()
            
            print(f"\n--- Batch {batch_num}/{n_batches} ({len(batch_ids)} hospitalizations) ---")
            
            # Process this batch
            batch_result = _process_hourly_single_batch(conn, batch_df, aggregation_config.copy())
            
            if len(batch_result) > 0:
                batch_results.append(batch_result)
                print(f"Batch {batch_num} completed: {len(batch_result)} records")
            
            # Clean up batch-specific tables
            try:
                conn.execute("DROP TABLE IF EXISTS hourly_base")
                conn.execute("DROP TABLE IF EXISTS hourly_data")
                conn.unregister('wide_data')
            except:
                pass
            
            # Explicit garbage collection between batches
            import gc
            gc.collect()
                
        except Exception as e:
            print(f"Error processing batch {batch_num}: {str(e)}")
            continue
    
    if batch_results:
        print(f"\nCombining {len(batch_results)} batch results...")
        final_df = pd.concat(batch_results, ignore_index=True)
        final_df = final_df.sort_values(['hospitalization_id', 'nth_hour']).reset_index(drop=True)
        
        print(f"Final hourly dataset: {len(final_df)} records from {len(batch_results)} batches")
        return final_df
    else:
        raise ValueError("No batches processed successfully")


def _build_aggregation_query_duckdb(
    conn: duckdb.DuckDBPyConnection,
    aggregation_config: Dict[str, List[str]],
    all_columns: List[str]
) -> Dict[str, str]:
    """Build separate DuckDB aggregation queries by type for better performance and progress tracking."""
    
    # Group by columns
    group_cols = ['hospitalization_id', 'event_time_hour', 'nth_hour', 'hour_bucket']
    
    # Get columns not in aggregation config
    all_agg_columns = []
    for columns_list in aggregation_config.values():
        all_agg_columns.extend(columns_list)
    
    non_agg_columns = [col for col in all_columns 
                      if col not in all_agg_columns 
                      and col not in group_cols
                      and col not in ['patient_id', 'day_number', 'first_event_hour', 'event_time']]
    
    if non_agg_columns:
        print("Columns not in aggregation_config, defaulting to 'first' with '_c' postfix:")
        for col in non_agg_columns:
            print(f"  - {col}")
        if 'first' not in aggregation_config:
            aggregation_config['first'] = []
        aggregation_config['first'].extend(non_agg_columns)
    
    # Build separate queries for each aggregation type
    queries = {}
    
    # Base columns query
    base_query = f"""
    SELECT 
        hospitalization_id,
        event_time_hour, 
        nth_hour,
        hour_bucket,
        FIRST(patient_id) AS patient_id,
        FIRST(day_number) AS day_number
    FROM hourly_data
    GROUP BY hospitalization_id, event_time_hour, nth_hour, hour_bucket
    """
    queries['base'] = base_query
    
    # Process each aggregation type separately
    for agg_method, columns in aggregation_config.items():
        if agg_method == 'one_hot_encode':
            continue  # Handle separately
            
        valid_columns = [col for col in columns if col in all_columns]
        if not valid_columns:
            continue
            
        select_parts = ['hospitalization_id', 'event_time_hour', 'nth_hour', 'hour_bucket']
        
        for col in valid_columns:
            if agg_method == 'max':
                select_parts.append(f"MAX({col}) AS {col}_max")
            elif agg_method == 'min':
                select_parts.append(f"MIN({col}) AS {col}_min")
            elif agg_method == 'mean':
                select_parts.append(f"AVG({col}) AS {col}_mean")
            elif agg_method == 'median':
                select_parts.append(f"MEDIAN({col}) AS {col}_median")
            elif agg_method == 'first':
                if col in non_agg_columns:
                    select_parts.append(f"FIRST({col}) AS {col}_c")
                else:
                    select_parts.append(f"FIRST({col}) AS {col}_first")
            elif agg_method == 'last':
                select_parts.append(f"LAST({col}) AS {col}_last")
            elif agg_method == 'boolean':
                select_parts.append(f"CASE WHEN COUNT({col}) > 0 THEN 1 ELSE 0 END AS {col}_boolean")
        
        query = f"""
        SELECT 
            {', '.join(select_parts)}
        FROM hourly_data
        GROUP BY hospitalization_id, event_time_hour, nth_hour, hour_bucket
        """
        queries[agg_method] = query
    
    # Handle one-hot encoding separately
    if 'one_hot_encode' in aggregation_config:
        one_hot_query = _build_one_hot_encoding_query_duckdb(
            conn, aggregation_config['one_hot_encode'], all_columns
        )
        if one_hot_query:
            queries['one_hot_encode'] = one_hot_query
    
    return queries


def _build_one_hot_encoding_query_duckdb(
    conn: duckdb.DuckDBPyConnection,
    one_hot_columns: List[str],
    all_columns: List[str]
) -> Optional[str]:
    """Build a separate query for one-hot encoding."""
    
    valid_columns = [col for col in one_hot_columns if col in all_columns]
    if not valid_columns:
        return None
    
    select_parts = ['hospitalization_id', 'event_time_hour', 'nth_hour', 'hour_bucket']
    
    for col in valid_columns:
        # Get unique values for this column
        unique_vals_query = f"""
        SELECT DISTINCT {col} 
        FROM hourly_data 
        WHERE {col} IS NOT NULL
        ORDER BY {col}
        LIMIT 100  -- Limit to prevent too many columns
        """
        
        try:
            unique_vals_result = conn.execute(unique_vals_query).fetchall()
            
            if len(unique_vals_result) > 50:
                print(f"Warning: {col} has {len(unique_vals_result)} unique values. One-hot encoding may create many columns.")
            
            # Create conditional aggregation for each unique value
            for (val,) in unique_vals_result:
                # Clean column name
                clean_val = re.sub(r'[^a-zA-Z0-9_]', '_', str(val))
                col_name = f"{col}_{clean_val}"
                
                # Handle string values with proper escaping
                if isinstance(val, str):
                    val_escaped = val.replace("'", "''")
                    select_parts.append(f"MAX(CASE WHEN {col} = '{val_escaped}' THEN 1 ELSE 0 END) AS {col_name}")
                else:
                    select_parts.append(f"MAX(CASE WHEN {col} = {val} THEN 1 ELSE 0 END) AS {col_name}")
                    
        except Exception as e:
            print(f"Warning: Could not create one-hot encoding for {col}: {str(e)}")
    
    if len(select_parts) > 4:  # More than just the group by columns
        query = f"""
        SELECT 
            {', '.join(select_parts)}
        FROM hourly_data
        GROUP BY hospitalization_id, event_time_hour, nth_hour, hour_bucket
        """
        return query
    
    return None


def convert_wide_to_hourly(
    wide_df: pd.DataFrame, 
    aggregation_config: Dict[str, List[str]], 
    memory_limit: str = '4GB',
    temp_directory: Optional[str] = None,
    batch_size: Optional[int] = None
) -> pd.DataFrame:
    """
    Convert a wide dataset to hourly aggregation with user-defined aggregation methods.
    
    This function uses DuckDB for high-performance aggregation.
    
    Parameters:
        wide_df: Wide dataset DataFrame from create_wide_dataset()
        aggregation_config: Dict mapping aggregation methods to list of columns
            Example: {
                'max': ['map', 'temp_c', 'sbp'],
                'mean': ['heart_rate', 'respiratory_rate'],
                'min': ['spo2'],
                'median': ['glucose'],
                'first': ['gcs_total', 'rass'],
                'last': ['assessment_value'],
                'boolean': ['norepinephrine', 'propofol'],
                'one_hot_encode': ['medication_name', 'assessment_category']
            }
        memory_limit: DuckDB memory limit (e.g., '4GB', '8GB')
        temp_directory: Directory for temporary files (default: system temp)
        batch_size: Process in batches if dataset is large (auto-determined if None)
    
    Returns:
        pd.DataFrame: Hourly aggregated wide dataset with nth_hour column
    """
    
    return convert_wide_to_hourly_optimized(
        wide_df, aggregation_config, memory_limit, temp_directory, batch_size
    )




def _process_hospitalizations(
    conn: duckdb.DuckDBPyConnection,
    clif_instance,
    required_ids: List[str],
    patient_df: pd.DataFrame,
    hospitalization_df: pd.DataFrame,
    adt_df: pd.DataFrame,
    tables_to_load: List[str],
    category_filters: Dict[str, List[str]],
    pivot_tables: List[str],
    wide_tables: List[str],
    show_progress: bool,
    cohort_df: Optional[pd.DataFrame] = None
) -> Optional[pd.DataFrame]:
    """Process hospitalizations with pivot-first approach."""
    
    print("\n=== Processing Tables ===")
    
    # Create base cohort
    base_cohort = pd.merge(hospitalization_df, patient_df, on='patient_id', how='inner')
    print(f"Base cohort created with {len(base_cohort)} records")
    
    # Register base tables as proper tables, not views
    conn.register('temp_base', base_cohort)
    conn.execute("CREATE OR REPLACE TABLE base_cohort AS SELECT * FROM temp_base")
    conn.unregister('temp_base')
    
    conn.register('temp_adt', adt_df)
    conn.execute("CREATE OR REPLACE TABLE adt AS SELECT * FROM temp_adt")
    conn.unregister('temp_adt')
    
    # Dictionaries to store table info
    event_time_queries = []
    pivoted_table_names = {}
    raw_table_names = {}
    
    # Add ADT event times
    if 'in_dttm' in adt_df.columns:
        event_time_queries.append("""
            SELECT DISTINCT hospitalization_id, in_dttm AS event_time 
            FROM adt 
            WHERE in_dttm IS NOT NULL
        """)
    
    # Process tables to load
    for table_name in tables_to_load:
        print(f"\nProcessing {table_name}...")
        
        # Get table data
        table_attr = 'lab' if table_name == 'labs' else table_name
        table_obj = getattr(clif_instance, table_attr, None)
        
        if table_obj is None:
            print(f"Warning: {table_name} not loaded in CLIF instance, skipping...")
            continue
            
        # Filter by hospitalization IDs immediately
        table_df = table_obj.df[table_obj.df['hospitalization_id'].isin(required_ids)].copy()
        
        if len(table_df) == 0:
            print(f"No data found in {table_name} for selected hospitalizations")
            continue
        
        # For wide tables (non-pivot), filter columns based on category_filters
        if table_name in wide_tables and table_name in category_filters:
            # For respiratory_support, category_filters contains column names to keep
            required_cols = ['hospitalization_id']  # Always keep hospitalization_id
            timestamp_col = _get_timestamp_column(table_name)
            if timestamp_col:
                required_cols.append(timestamp_col)
            
            # Add the columns specified in category_filters
            specified_cols = category_filters[table_name]
            required_cols.extend(specified_cols)
            
            # Filter to only available columns
            available_cols = [col for col in required_cols if col in table_df.columns]
            missing_cols = [col for col in required_cols if col not in table_df.columns]
            
            if missing_cols:
                print(f"Warning: Columns not found in {table_name}: {missing_cols}")
            
            if available_cols:
                table_df = table_df[available_cols].copy()
                print(f"Filtered {table_name} to {len(available_cols)} columns: {available_cols}")
            
        print(f"Loaded {len(table_df)} records from {table_name}")
        
        # Get timestamp column
        timestamp_col = _get_timestamp_column(table_name)
        if timestamp_col and timestamp_col not in table_df.columns:
            timestamp_col = _find_alternative_timestamp(table_name, table_df.columns)
        
        if not timestamp_col or timestamp_col not in table_df.columns:
            print(f"Warning: No timestamp column found for {table_name}, skipping...")
            continue
        
        # Apply time filtering if cohort_df is provided
        if cohort_df is not None:
            pre_filter_count = len(table_df)
            # Merge with cohort_df to get time windows
            table_df = pd.merge(
                table_df,
                cohort_df[['hospitalization_id', 'start_time', 'end_time']],
                on='hospitalization_id',
                how='inner'
            )
            
            # Ensure timestamp column is datetime
            if not pd.api.types.is_datetime64_any_dtype(table_df[timestamp_col]):
                table_df[timestamp_col] = pd.to_datetime(table_df[timestamp_col])
            
            # Filter to time window
            table_df = table_df[
                (table_df[timestamp_col] >= table_df['start_time']) &
                (table_df[timestamp_col] <= table_df['end_time'])
            ].copy()
            
            # Drop the time window columns
            table_df = table_df.drop(columns=['start_time', 'end_time'])
            
            print(f"  Time filtering: {pre_filter_count} → {len(table_df)} records")
        
        # Register raw table as a proper table, not a view
        raw_table_name = f"{table_name}_raw"
        # First register the DataFrame temporarily
        conn.register('temp_df', table_df)
        # Create a proper table from it
        conn.execute(f"CREATE OR REPLACE TABLE {raw_table_name} AS SELECT * FROM temp_df")
        # Clean up the temporary registration
        conn.unregister('temp_df')
        raw_table_names[table_name] = raw_table_name
        
        # Process based on table type
        if table_name in pivot_tables:
            # Pivot the table first
            pivoted_name = _pivot_table_duckdb(conn, table_name, table_df, timestamp_col, category_filters)
            if pivoted_name:
                pivoted_table_names[table_name] = pivoted_name
                # Add event times from the RAW table (not pivoted)
                event_time_queries.append(f"""
                    SELECT DISTINCT hospitalization_id, {timestamp_col} AS event_time 
                    FROM {raw_table_name} 
                    WHERE {timestamp_col} IS NOT NULL
                """)
        else:
            # Wide table - just add event times
            event_time_queries.append(f"""
                SELECT DISTINCT hospitalization_id, {timestamp_col} AS event_time 
                FROM {raw_table_name} 
                WHERE {timestamp_col} IS NOT NULL
            """)
    
    # Now create the union and join
    if event_time_queries:
        print("\n=== Creating wide dataset ===")
        final_df = _create_wide_dataset(
            conn, base_cohort, event_time_queries, 
            pivoted_table_names, raw_table_names, 
            tables_to_load, pivot_tables, 
            category_filters
        )
        return final_df
    else:
        print("No event times found, returning base cohort only")
        return base_cohort


def _pivot_table_duckdb(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    table_df: pd.DataFrame,
    timestamp_col: str,
    category_filters: Dict[str, List[str]]
) -> Optional[str]:
    """Pivot a table and return the pivoted table name."""
    
    # Get column mappings
    category_col_mapping = {
        'vitals': 'vital_category',
        'labs': 'lab_category', 
        'medication_admin_continuous': 'med_category',
        'patient_assessments': 'assessment_category'
    }
    
    value_col_mapping = {
        'vitals': 'vital_value',
        'labs': 'lab_value_numeric',
        'medication_admin_continuous': 'med_dose',
        'patient_assessments': 'assessment_value'
    }
    
    category_col = category_col_mapping.get(table_name)
    value_col = value_col_mapping.get(table_name)
    
    if not category_col or not value_col:
        print(f"Warning: No pivot configuration for {table_name}")
        return None
    
    if category_col not in table_df.columns or value_col not in table_df.columns:
        print(f"Warning: Required columns {category_col} or {value_col} not found in {table_name}")
        return None
    
    # Build filter clause if categories specified
    filter_clause = ""
    if table_name in category_filters and category_filters[table_name]:
        categories_list = "','".join(category_filters[table_name])
        filter_clause = f"AND {category_col} IN ('{categories_list}')"
        print(f"Filtering {table_name} categories to: {category_filters[table_name]}")
    
    # Create pivot query
    pivoted_table_name = f"{table_name}_pivoted"
    pivot_query = f"""
    CREATE OR REPLACE TABLE {pivoted_table_name} AS
    WITH pivot_data AS (
        SELECT DISTINCT 
            {value_col}, 
            {category_col},
            hospitalization_id || '_' || strftime({timestamp_col}, '%Y%m%d%H%M') AS combo_id
        FROM {table_name}_raw 
        WHERE {timestamp_col} IS NOT NULL {filter_clause}
    ) 
    PIVOT pivot_data
    ON {category_col}
    USING first({value_col})
    GROUP BY combo_id
    """
    
    try:
        conn.execute(pivot_query)
        
        # Get stats
        count = conn.execute(f"SELECT COUNT(*) FROM {pivoted_table_name}").fetchone()[0]
        cols = len(conn.execute(f"SELECT * FROM {pivoted_table_name} LIMIT 0").df().columns) - 1
        
        print(f"Pivoted {table_name}: {count} combo_ids with {cols} category columns")
        return pivoted_table_name
        
    except Exception as e:
        print(f"Error pivoting {table_name}: {str(e)}")
        return None


def _create_wide_dataset(
    conn: duckdb.DuckDBPyConnection,
    base_cohort: pd.DataFrame,
    event_time_queries: List[str],
    pivoted_table_names: Dict[str, str],
    raw_table_names: Dict[str, str],
    tables_to_load: List[str],
    pivot_tables: List[str],
    category_filters: Dict[str, List[str]]
) -> pd.DataFrame:
    """Create the final wide dataset by joining all tables."""
    
    # Create union of all event times
    union_query = " UNION ALL ".join(event_time_queries)
    
    # Build the main query
    query = f"""
    WITH all_events AS (
        SELECT DISTINCT hospitalization_id, event_time
        FROM ({union_query}) uni_time
    ),
    expanded_cohort AS (
        SELECT 
            a.*,
            b.event_time,
            a.hospitalization_id || '_' || strftime(b.event_time, '%Y%m%d%H%M') AS combo_id
        FROM base_cohort a
        INNER JOIN all_events b ON a.hospitalization_id = b.hospitalization_id
    )
    SELECT ec.*
    """
    
    # Add ADT columns
    if 'adt' in conn.execute("SHOW TABLES").df()['name'].values:
        adt_cols = [col for col in conn.execute("SELECT * FROM adt LIMIT 0").df().columns 
                   if col not in ['hospitalization_id']]
        if adt_cols:
            adt_col_list = ', '.join([f"adt_combo.{col}" for col in adt_cols])
            query = query.replace("SELECT ec.*", f"SELECT ec.*, {adt_col_list}")
    
    # Add pivoted table columns
    for table_name, pivoted_table_name in pivoted_table_names.items():
        pivot_cols = conn.execute(f"SELECT * FROM {pivoted_table_name} LIMIT 0").df().columns
        pivot_cols = [col for col in pivot_cols if col != 'combo_id']
        
        if pivot_cols:
            pivot_col_list = ', '.join([f"{pivoted_table_name}.{col}" for col in pivot_cols])
            query = query.replace("SELECT ec.*", f"SELECT ec.*, {pivot_col_list}")
    
    # Add non-pivoted table columns (respiratory_support)
    for table_name in tables_to_load:
        if table_name not in pivot_tables and table_name in raw_table_names:
            timestamp_col = _get_timestamp_column(table_name)
            if not timestamp_col:
                continue
                
            raw_cols = conn.execute(f"SELECT * FROM {raw_table_names[table_name]} LIMIT 0").df().columns
            table_cols = [col for col in raw_cols if col not in ['hospitalization_id', timestamp_col]]
            
            if table_cols:
                col_list = ', '.join([f"{table_name}_combo.{col}" for col in table_cols])
                query = query.replace("SELECT ec.*", f"SELECT ec.*, {col_list}")
    
    # Add FROM clause
    query += " FROM expanded_cohort ec"
    
    # Add ADT join
    if 'adt' in conn.execute("SHOW TABLES").df()['name'].values:
        query += """
        LEFT JOIN (
            SELECT 
                hospitalization_id || '_' || strftime(in_dttm, '%Y%m%d%H%M') AS combo_id,
                *
            FROM adt
            WHERE in_dttm IS NOT NULL
        ) adt_combo USING (combo_id)
        """
    
    # Add joins for pivoted tables
    for table_name, pivoted_table_name in pivoted_table_names.items():
        query += f" LEFT JOIN {pivoted_table_name} USING (combo_id)"
    
    # Add joins for non-pivoted tables
    for table_name in tables_to_load:
        if table_name not in pivot_tables and table_name in raw_table_names:
            timestamp_col = _get_timestamp_column(table_name)
            if timestamp_col:
                raw_cols = conn.execute(f"SELECT * FROM {raw_table_names[table_name]} LIMIT 0").df().columns
                if timestamp_col in raw_cols:
                    table_cols = [col for col in raw_cols if col not in ['hospitalization_id', timestamp_col]]
                    if table_cols:
                        col_list = ', '.join(table_cols)
                        query += f"""
                        LEFT JOIN (
                            SELECT 
                                hospitalization_id || '_' || strftime({timestamp_col}, '%Y%m%d%H%M') AS combo_id,
                                {col_list}
                            FROM {raw_table_names[table_name]}
                            WHERE {timestamp_col} IS NOT NULL
                        ) {table_name}_combo USING (combo_id)
                        """
    
    # Execute query
    print("Executing join query...")
    result_df = conn.execute(query).df()
    
    # Remove duplicate columns
    result_df = result_df.loc[:, ~result_df.columns.duplicated()]
    
    # Add day-based columns
    result_df['date'] = pd.to_datetime(result_df['event_time']).dt.date
    result_df = result_df.sort_values(['hospitalization_id', 'event_time']).reset_index(drop=True)
    result_df['day_number'] = result_df.groupby('hospitalization_id')['date'].rank(method='dense').astype(int)
    result_df['hosp_id_day_key'] = (result_df['hospitalization_id'].astype(str) + '_day_' + 
                                    result_df['day_number'].astype(str))
    
    # Add missing columns for requested categories
    _add_missing_columns(result_df, category_filters, tables_to_load)
    
    # Clean up
    columns_to_drop = ['combo_id', 'date']
    result_df = result_df.drop(columns=[col for col in columns_to_drop if col in result_df.columns])
    
    print(f"Wide dataset created: {len(result_df)} records with {len(result_df.columns)} columns")
    
    return result_df


def _add_missing_columns(
    df: pd.DataFrame, 
    category_filters: Dict[str, List[str]], 
    tables_loaded: List[str]
):
    """Add missing columns for categories that were requested but not found in data."""
    
    if not category_filters:
        return
    
    for table_name, categories in category_filters.items():
        if table_name in tables_loaded and categories:
            for category in categories:
                if category not in df.columns:
                    df[category] = np.nan
                    print(f"Added missing column: {category}")


def _process_in_batches(
    conn: duckdb.DuckDBPyConnection,
    clif_instance,
    all_hosp_ids: List[str],
    patient_df: pd.DataFrame,
    hospitalization_df: pd.DataFrame,
    adt_df: pd.DataFrame,
    tables_to_load: List[str],
    category_filters: Dict[str, List[str]],
    pivot_tables: List[str],
    wide_tables: List[str],
    batch_size: int,
    show_progress: bool,
    save_to_data_location: bool,
    output_filename: Optional[str],
    output_format: str,
    return_dataframe: bool,
    cohort_df: Optional[pd.DataFrame] = None
) -> Optional[pd.DataFrame]:
    """Process hospitalizations in batches using the new approach."""
    
    # Split into batches
    batches = [all_hosp_ids[i:i + batch_size] for i in range(0, len(all_hosp_ids), batch_size)]
    batch_results = []
    
    iterator = tqdm(batches, desc="Processing batches") if show_progress else batches
    
    for batch_idx, batch_hosp_ids in enumerate(iterator):
        try:
            print(f"\nProcessing batch {batch_idx + 1}/{len(batches)} ({len(batch_hosp_ids)} hospitalizations)")
            
            # Filter base tables for this batch
            batch_hosp_df = hospitalization_df[hospitalization_df['hospitalization_id'].isin(batch_hosp_ids)]
            batch_adt_df = adt_df[adt_df['hospitalization_id'].isin(batch_hosp_ids)]
            
            # Filter cohort_df for this batch if provided
            batch_cohort_df = None
            if cohort_df is not None:
                batch_cohort_df = cohort_df[cohort_df['hospitalization_id'].isin(batch_hosp_ids)].copy()
            
            # Clean up tables from previous batch
            tables_df = conn.execute("SHOW TABLES").df()
            for idx, row in tables_df.iterrows():
                table_name = row['name']
                if table_name not in ['base_cohort', 'adt']:
                    try:
                        # Try to drop as table first
                        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
                    except:
                        # If that fails, try to drop as view
                        try:
                            conn.execute(f"DROP VIEW IF EXISTS {table_name}")
                        except:
                            pass
            
            # Process this batch
            batch_result = _process_hospitalizations(
                conn, clif_instance, batch_hosp_ids, patient_df, batch_hosp_df, batch_adt_df,
                tables_to_load, category_filters, pivot_tables, wide_tables,
                show_progress=False, cohort_df=batch_cohort_df
            )
            
            if batch_result is not None and len(batch_result) > 0:
                batch_results.append(batch_result)
                print(f"Batch {batch_idx + 1} completed: {len(batch_result)} records")
            
            # Clean up after batch
            import gc
            gc.collect()
            
        except Exception as e:
            logger.error(f"Error processing batch {batch_idx + 1}: {str(e)}")
            print(f"Warning: Failed to process batch {batch_idx + 1}: {str(e)}")
            continue
    
    # Combine results
    if batch_results:
        print(f"\nCombining {len(batch_results)} batch results...")
        final_df = pd.concat(batch_results, ignore_index=True)
        print(f"Final dataset: {len(final_df)} records with {len(final_df.columns)} columns")
        
        if save_to_data_location:
            _save_dataset(final_df, clif_instance.data_dir, output_filename, output_format)
        
        return final_df if return_dataframe else None
    else:
        print("No data processed successfully")
        return None