"""
Demo dataset loading functions for pyCLIF.

Provides easy access to sample CLIF data for testing and demonstration.
Similar to sklearn's toy datasets but specific to CLIF format.
"""

import os
import pandas as pd
from typing import Dict, Optional, List, Union
from pathlib import Path


def _get_demo_data_path() -> str:
    """Get the path to demo data directory."""
    # Get the path relative to this file
    current_dir = Path(__file__).parent
    demo_path = current_dir / 'clif_demo'
    return str(demo_path.absolute())


def _load_demo_table(table_name: str, return_raw: bool = False) -> Union[pd.DataFrame, object]:
    """
    Load a single demo table.
    
    Parameters:
        table_name (str): Name of the table (e.g., 'patient', 'labs')
        return_raw (bool): If True, return raw DataFrame. If False, return table object.
        
    Returns:
        Union[pd.DataFrame, table_object]: Either raw DataFrame or wrapped table object
    """
    demo_path = _get_demo_data_path()
    file_path = os.path.join(demo_path, f'clif_{table_name}.parquet')
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Demo data file not found: {file_path}")
    
    # Load raw data
    df = pd.read_parquet(file_path)
    
    if return_raw:
        return df
    
    # Import table classes here to avoid circular imports
    from ..tables.patient import patient
    from ..tables.labs import labs
    from ..tables.vitals import vitals
    from ..tables.respiratory_support import respiratory_support
    from ..tables.position import position
    from ..tables.adt import adt
    from ..tables.hospitalization import hospitalization
    from ..tables.medication_admin_continuous import medication_admin_continuous
    from ..tables.patient_assessments import patient_assessments
    
    # Return wrapped table object
    table_classes = {
        'patient': patient,
        'labs': labs,
        'vitals': vitals,
        'respiratory_support': respiratory_support,
        'position': position,
        'adt': adt,
        'hospitalization': hospitalization,
        'medication_admin_continuous': medication_admin_continuous,
        'patient_assessments': patient_assessments
    }
    
    if table_name in table_classes:
        # Create table object without validation to speed up demo loading
        table_obj = table_classes[table_name](df)
        return table_obj
    else:
        raise ValueError(f"Unknown table name: {table_name}")


def load_demo_clif(tables: Optional[List[str]] = None, timezone: str = "UTC", verbose: bool = False) -> object:
    """
    Load a complete CLIF object with demo data.
    
    Parameters:
        tables (List[str], optional): List of tables to load. If None, loads all available.
        timezone (str): Timezone for datetime conversion. Default is "UTC".
        verbose (bool): If True, show detailed loading messages. Default is False for cleaner output.
        
    Returns:
        CLIF: Initialized CLIF object with demo data
        
    Examples:
        >>> from pyclif.data import load_demo_clif
        >>> clif_demo = load_demo_clif()
        >>> print(f"Patients: {len(clif_demo.patient.df)}")
        >>> 
        >>> # Load only specific tables
        >>> clif_subset = load_demo_clif(tables=['patient', 'labs', 'vitals'])
        >>> 
        >>> # Load with detailed output
        >>> clif_verbose = load_demo_clif(verbose=True)
    """
    from ..clif import CLIF
    
    demo_path = _get_demo_data_path()
    
    # Initialize CLIF object with demo data path
    if not verbose:
        # Temporarily suppress print statements for cleaner demo output
        import sys
        from io import StringIO
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        
    try:
        clif_obj = CLIF(demo_path, filetype='parquet', timezone=timezone)
    finally:
        if not verbose:
            sys.stdout = old_stdout
    
    # Available tables in demo data
    available_tables = [
        'patient', 'hospitalization', 'labs', 'vitals', 
        'respiratory_support', 'position', 'adt',
        'medication_admin_continuous', 'patient_assessments'
    ]
    
    if tables is None:
        tables = available_tables
    else:
        # Validate requested tables
        invalid_tables = set(tables) - set(available_tables)
        if invalid_tables:
            raise ValueError(f"Invalid table names: {invalid_tables}. Available: {available_tables}")
    
    # Load requested tables
    if not verbose:
        # Suppress output during table loading
        import sys
        from io import StringIO
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        
    try:
        clif_obj.initialize(tables=tables)
    finally:
        if not verbose:
            sys.stdout = old_stdout
    
    if not verbose:
        print(f"📊 Demo dataset loaded successfully!")
        print(f"   Tables: {', '.join(tables)}")
        if hasattr(clif_obj, 'patient') and clif_obj.patient:
            print(f"   Patients: {len(clif_obj.patient.df)} unique patients")
    
    return clif_obj


# Individual table loading functions
def load_demo_patient(return_raw: bool = False):
    """
    Load demo patient data.
    
    Parameters:
        return_raw (bool): If True, return raw DataFrame. If False, return patient object.
        
    Returns:
        Union[pd.DataFrame, patient]: Patient data
        
    Examples:
        >>> from pyclif.data import load_demo_patient
        >>> patient_data = load_demo_patient()
        >>> print(f"Number of patients: {len(patient_data.df)}")
        >>> 
        >>> # Get raw DataFrame
        >>> patient_df = load_demo_patient(return_raw=True)
        >>> print(patient_df.head())
    """
    return _load_demo_table('patient', return_raw)


def load_demo_labs(return_raw: bool = False):
    """
    Load demo labs data.
    
    Parameters:
        return_raw (bool): If True, return raw DataFrame. If False, return labs object.
        
    Returns:
        Union[pd.DataFrame, labs]: Labs data
    """
    return _load_demo_table('labs', return_raw)


def load_demo_vitals(return_raw: bool = False):
    """
    Load demo vitals data.
    
    Parameters:
        return_raw (bool): If True, return raw DataFrame. If False, return vitals object.
        
    Returns:
        Union[pd.DataFrame, vitals]: Vitals data
    """
    return _load_demo_table('vitals', return_raw)


def load_demo_respiratory_support(return_raw: bool = False):
    """
    Load demo respiratory support data.
    
    Parameters:
        return_raw (bool): If True, return raw DataFrame. If False, return respiratory_support object.
        
    Returns:
        Union[pd.DataFrame, respiratory_support]: Respiratory support data
    """
    return _load_demo_table('respiratory_support', return_raw)


def load_demo_position(return_raw: bool = False):
    """
    Load demo position data.
    
    Parameters:
        return_raw (bool): If True, return raw DataFrame. If False, return position object.
        
    Returns:
        Union[pd.DataFrame, position]: Position data
    """
    return _load_demo_table('position', return_raw)


def load_demo_adt(return_raw: bool = False):
    """
    Load demo ADT data.
    
    Parameters:
        return_raw (bool): If True, return raw DataFrame. If False, return adt object.
        
    Returns:
        Union[pd.DataFrame, adt]: ADT data
    """
    return _load_demo_table('ADT', return_raw)


def load_demo_hospitalization(return_raw: bool = False):
    """
    Load demo hospitalization data.
    
    Parameters:
        return_raw (bool): If True, return raw DataFrame. If False, return hospitalization object.
        
    Returns:
        Union[pd.DataFrame, hospitalization]: Hospitalization data
    """
    return _load_demo_table('hospitalization', return_raw)


def load_demo_medication_admin_continuous(return_raw: bool = False):
    """
    Load demo medication admin continuous data.
    
    Parameters:
        return_raw (bool): If True, return raw DataFrame. If False, return medication_admin_continuous object.
        
    Returns:
        Union[pd.DataFrame, medication_admin_continuous]: Medication admin continuous data
    """
    return _load_demo_table('medication_admin_continuous', return_raw)


def load_demo_patient_assessments(return_raw: bool = False):
    """
    Load demo patient assessments data.
    
    Parameters:
        return_raw (bool): If True, return raw DataFrame. If False, return patient_assessments object.
        
    Returns:
        Union[pd.DataFrame, patient_assessments]: Patient assessments data
    """
    return _load_demo_table('patient_assessments', return_raw)


def list_demo_datasets() -> Dict[str, Dict[str, Union[int, str]]]:
    """
    List all available demo datasets with basic information.
    
    Returns:
        Dict: Information about each demo dataset
        
    Examples:
        >>> from pyclif.data import list_demo_datasets
        >>> datasets_info = list_demo_datasets()
        >>> for name, info in datasets_info.items():
        ...     print(f"{name}: {info['rows']} rows, {info['size']}")
    """
    demo_path = _get_demo_data_path()
    datasets_info = {}
    
    table_names = [
        'patient', 'hospitalization', 'labs', 'vitals', 
        'respiratory_support', 'position', 'adt',
        'medication_admin_continuous', 'patient_assessments'
    ]
    
    for table_name in table_names:
        file_path = os.path.join(demo_path, f'clif_{table_name}.parquet')
        if os.path.exists(file_path):
            try:
                df = pd.read_parquet(file_path)
                file_size = os.path.getsize(file_path)
                
                # Convert file size to human readable format
                if file_size < 1024:
                    size_str = f"{file_size} B"
                elif file_size < 1024 * 1024:
                    size_str = f"{file_size / 1024:.1f} KB"
                else:
                    size_str = f"{file_size / (1024 * 1024):.1f} MB"
                
                datasets_info[table_name] = {
                    'rows': len(df),
                    'columns': len(df.columns),
                    'size': size_str,
                    'file_path': file_path
                }
            except Exception as e:
                datasets_info[table_name] = {
                    'error': str(e),
                    'file_path': file_path
                }
    
    return datasets_info


def get_demo_summary() -> None:
    """
    Print a summary of all available demo datasets.
    
    Examples:
        >>> from pyclif.data import get_demo_summary
        >>> get_demo_summary()
    """
    datasets_info = list_demo_datasets()
    
    print("🏥 pyCLIF Demo Datasets Summary")
    print("=" * 50)
    
    total_rows = 0
    for name, info in datasets_info.items():
        if 'error' not in info:
            print(f"{name:30} | {info['rows']:6,} rows | {info['columns']:2} cols | {info['size']:>8}")
            total_rows += info['rows']
        else:
            print(f"{name:30} | ERROR: {info['error']}")
    
    print("=" * 50)
    print(f"{'Total records':30} | {total_rows:6,} rows")
    print()
    print("📖 Usage examples:")
    print("  from pyclif.data import load_demo_clif, load_demo_patient")
    print("  clif_demo = load_demo_clif()  # Load all tables")
    print("  patient_data = load_demo_patient()  # Load single table")
    print("  raw_df = load_demo_labs(return_raw=True)  # Get raw DataFrame")