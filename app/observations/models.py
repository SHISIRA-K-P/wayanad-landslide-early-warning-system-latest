from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class EmergencyAuthority(models.Model):
    class AuthorityType(models.TextChoices):
        DISASTER_MANAGEMENT = 'disaster_management', 'Disaster Management'
        DISTRICT_ADMINISTRATION = 'district_administration', 'District Administration'
        POLICE = 'police', 'Police'
        FIRE_RESCUE = 'fire_rescue', 'Fire and Rescue'
        OTHER = 'other', 'Other'

    authority_name = models.CharField(max_length=200)
    authority_type = models.CharField(
        max_length=32,
        choices=AuthorityType.choices,
        default=AuthorityType.OTHER,
    )
    location_id = models.PositiveIntegerField(db_index=True)
    district = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone_number = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(
        default=False,
        help_text='Enable only after checking this contact against an official source.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['authority_name', 'id']
        db_table = 'EmergencyAuthority'

    def __str__(self):
        return f'{self.authority_name} (location {self.location_id})'


class LandslideObservation(models.Model):
    class VegetationCover(models.TextChoices):
        LOW = 'Low', 'Low'
        MEDIUM = 'Medium', 'Medium'
        HIGH = 'High', 'High'

    class LandslideStatus(models.TextChoices):
        YES = 'Yes', 'Yes'
        NO = 'No', 'No'

    location_id = models.IntegerField(validators=[MinValueValidator(1)])
    max_temp_c = models.FloatField()
    humidity_pct = models.FloatField(
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    wind_speed_kmh = models.FloatField(validators=[MinValueValidator(0)])
    rainfall_mm = models.FloatField(validators=[MinValueValidator(0)])
    slope_angle_deg = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(90)]
    )
    vegetation_cover = models.CharField(
        max_length=6,
        choices=VegetationCover.choices,
    )
    landslide_observed = models.CharField(
        max_length=3,
        choices=LandslideStatus.choices,
        blank=True,
        null=True,
    )
    landslide_prediction = models.CharField(
        max_length=3,
        choices=LandslideStatus.choices,
        blank=True,
        null=True,
    )
    landslide_probability = models.FloatField(
        blank=True,
        null=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'Observation {self.pk} - location {self.location_id}'
