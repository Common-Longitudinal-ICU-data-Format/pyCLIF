from datetime import datetime
from enum import Enum
from pydantic import BaseModel, model_validator


class VitalCategory(str, Enum):
    SBP = "sbp"
    DBP = "dbp"
    MAP = "map"
    RESPIRATORY_RATE = "respiratory_rate"
    TEMP_C = "temp_c"
    WEIGHT_KG = "weight_kg"
    HEIGHT_CM = "height_cm"
    SPO2 = "spo2"
    HEART_RATE = "heart_rate"


VITAL_VALUE_RANGES = {
    "height_cm": (76, 255),
    "weight_kg": (30, 1100),
    "sbp": (0, 300),
    "dbp": (0, 200),
    "map": (0, 250),
    "heart_rate": (0, 300),
    "respiratory_rate": (0, 60),
    "spo2": (50, 100),
    "temp_c": (32, 44)
}


class Vital(BaseModel):
    hospitalization_id: str
    recorded_dttm: datetime
    vital_name: str
    vital_category: VitalCategory
    vital_value: float
    meas_site_name: str

    @model_validator(mode="after")
    def validate_vital_value_range(cls, values):
        vital_category = values.get('vital_category')
        vital_value = values.get('vital_value')

        min_val, max_val = VITAL_VALUE_RANGES[vital_category]
        
        if not min_val <= vital_value <= max_val:
            raise ValueError(f'Vital value {vital_value} for {vital_category} must be between {min_val} and {max_val}')
        
        return values 
    
    --