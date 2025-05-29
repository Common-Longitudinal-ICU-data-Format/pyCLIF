from datetime import datetime
from enum import Enum
from pydantic import BaseModel, model_validator
from typing import Dict, Tuple


class LabOrderCategory(str, Enum):
    ABG = "ABG"
    BMP = "BMP"
    CBC = "CBC"
    COAGS = "Coags"
    LFT = "LFT"
    LACTIC_ACID = "Lactic Acid"
    MISC = "Misc"
    VBG = "VBG"


class LabCategory(str, Enum):
    ALBUMIN = "albumin"
    ALKALINE_PHOSPHATASE = "alkaline_phosphatase"
    ALT = "alt"
    AST = "ast"
    BASOPHILS_PERCENT = "basophils_percent"
    BASOPHILS_ABSOLUTE = "basophils_absolute"
    BICARBONATE = "bicarbonate"
    BILIRUBIN_TOTAL = "bilirubin_total"
    BILIRUBIN_CONJUGATED = "bilirubin_conjugated"
    BILIRUBIN_UNCONJUGATED = "bilirubin_unconjugated"
    BUN = "bun"
    CALCIUM_TOTAL = "calcium_total"
    CALCIUM_IONIZED = "calcium_ionized"
    CHLORIDE = "chloride"
    CREATININE = "creatinine"
    CRP = "crp"
    EOSINOPHILS_PERCENT = "eosinophils_percent"
    EOSINOPHILS_ABSOLUTE = "eosinophils_absolute"
    ESR = "esr"
    FERRITIN = "ferritin"
    GLUCOSE_FINGERSTICK = "glucose_fingerstick"
    GLUCOSE_SERUM = "glucose_serum"
    HEMOGLOBIN = "hemoglobin"
    PHOSPHATE = "phosphate"
    INR = "inr"
    LACTATE = "lactate"
    LDH = "ldh"
    LYMPHOCYTES_PERCENT = "lymphocytes_percent"
    LYMPHOCYTES_ABSOLUTE = "lymphocytes_absolute"
    MAGNESIUM = "magnesium"
    MONOCYTES_PERCENT = "monocytes_percent"
    MONOCYTES_ABSOLUTE = "monocytes_absolute"
    NEUTROPHILS_PERCENT = "neutrophils_percent"
    NEUTROPHILS_ABSOLUTE = "neutrophils_absolute"
    PCO2_ARTERIAL = "pco2_arterial"
    PO2_ARTERIAL = "po2_arterial"
    PCO2_VENOUS = "pco2_venous"
    PH_ARTERIAL = "ph_arterial"
    PH_VENOUS = "ph_venous"
    PLATELET_COUNT = "platelet_count"
    POTASSIUM = "potassium"
    PROCALCITONIN = "procalcitonin"
    PT = "pt"
    PTT = "ptt"
    SO2_ARTERIAL = "so2_arterial"
    SO2_MIXED_VENOUS = "so2_mixed_venous"
    SO2_CENTRAL_VENOUS = "so2_central_venous"
    SODIUM = "sodium"
    TOTAL_PROTEIN = "total_protein"
    TROPONIN_I = "troponin_i"
    TROPONIN_T = "troponin_t"
    WBC = "wbc"


class LabSpecimenCategory(str, Enum):
    pass

LAB_VALUE_RANGES: Dict[str, Tuple[float, float]] = {
    "albumin": (0, 15),
    "alkaline_phosphatase": (0, 5000),
    "alt": (0, 20000),
    "ast": (0, 20000),
    "basophils_percent": (0, 100),
    "basophils_absolute": (0, 50),
    "bicarbonate": (0, 50),
    "bilirubin_total": (0, 80),
    "bilirubin_conjugated": (0, 50),
    "bilirubin_unconjugated": (0, 50),
    "bun": (0, 250),
    "calcium_total": (0, 20),
    "calcium_ionized": (0, 20),
    "chloride": (50, 140),
    "creatinine": (0, 20),
    "crp": (0, 1000),
    "eosinophils_percent": (0, 100),
    "eosinophils_absolute": (0, 50),
    "esr": (0, 1000),
    "ferritin": (0, 300000),
    "glucose_fingerstick": (0, 2000),
    "glucose_serum": (0, 2000),
    "hemoglobin": (2, 25),
    "phosphate": (0, 15),
    "inr": (0, 15),
    "lactate": (0, 30),
    "ldh": (0, 10000),
    "lymphocytes_percent": (0, 100),
    "lymphocytes_absolute": (0, 50),
    "magnesium": (0, 10),
    "monocytes_percent": (0, 100),
    "monocytes_absolute": (0, 50),
    "neutrophils_percent": (0, 100),
    "neutrophils_absolute": (0, 50),
    "pco2_arterial": (0, 250),
    "pco2_venous": (0, 250),
    "po2_arterial": (0, 700),
    "ph_arterial": (6, 10),
    "ph_venous": (5, 10),
    "platelet_count": (0, 2000),
    "potassium": (0, 15),
    "procalcitonin": (0, 1000),
    "pt": (1, 200),
    "ptt": (1, 200),
    "so2_arterial": (0, 100),
    "so2_mixed_venous": (0, 100),
    "so2_central_venous": (0, 100),
    "sodium": (90, 210),
    "total_protein": (0, 20),
    "troponin_i": (0, 10000),
    "troponin_t": (0, 10000),
    "wbc": (0, 500)
}

class Lab(BaseModel):
    hospitalization_id: str
    lab_order_dttm: datetime
    lab_collect_dttm: datetime
    lab_result_dttm: datetime
    lab_order_name: str
    lab_order_category: LabOrderCategory
    lab_name: str
    lab_category: LabCategory
    lab_value: str
    lab_value_numeric: float
    reference_unit: str
    lab_specimen_name: str
    lab_specimen_category: str  
    lab_loinc_code: str

    @model_validator(mode="after")
    def validate_lab_value_range(cls, values):
        lab_category = values.get('lab_category')
        lab_value_numeric = values.get('lab_value_numeric')

        min_val, max_val = LAB_VALUE_RANGES[lab_category]
        
        if not min_val <= lab_value_numeric <= max_val:
            raise ValueError(f'Lab value {lab_value_numeric} for {lab_category} must be between {min_val} and {max_val}')
        
        return values