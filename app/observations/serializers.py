# ============================================================
# IMPORTS
# ============================================================

from rest_framework import serializers
from .models import LandslideObservation


# ============================================================
# REQUEST SERIALIZERS
# ============================================================

class SafetyQuestionSerializer(serializers.Serializer):
    question = serializers.CharField(
        min_length=3,
        max_length=1000,
        trim_whitespace=True,
    )


# ============================================================
# OBSERVATION SERIALIZATION
# ============================================================

class LandslideObservationSerializer(serializers.ModelSerializer):
    DATASET_FIELD_NAMES = {
        'Location_ID': 'location_id',
        'Max_Temp_C': 'max_temp_c',
        'Humidity_Pct': 'humidity_pct',
        'Wind_Speed_kmh': 'wind_speed_kmh',
        'Rainfall_mm': 'rainfall_mm',
        'Slope_Angle_Deg': 'slope_angle_deg',
        'Vegetation_Cover': 'vegetation_cover',
    }

    class Meta:
        model = LandslideObservation
        fields = '__all__'
        read_only_fields = (
            'id',
            'created_at',
            'landslide_observed',
            'landslide_prediction',
            'landslide_probability',
        )

    def to_internal_value(self, data):
        translated_data = data.copy()
        for dataset_name, api_name in self.DATASET_FIELD_NAMES.items():
            if dataset_name not in data:
                continue
            if api_name in data:
                raise serializers.ValidationError({
                    dataset_name: (
                        f'Use either {dataset_name} or {api_name}, not both.'
                    )
                })
            translated_data[api_name] = translated_data.pop(dataset_name)
        return super().to_internal_value(translated_data)
