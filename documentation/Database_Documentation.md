# Database Documentation

The active Django database is configured in `app/config/settings.py` as
MySQL. `DB_NAME`, `DB_USER`, and `DB_PASSWORD` are required environment
variables; `DB_HOST` and `DB_PORT` default to `localhost` and `3306`.

Run schema migrations from the repository root:

```powershell
python app\manage.py migrate
```

## Current application tables

### `observations_landslideobservation`

This is Django's default table name for `LandslideObservation`, which does not
declare a custom `db_table`.

| Field | Django type | Meaning and constraints |
| --- | --- | --- |
| `id` | BigAutoField primary key | Automatically generated record identifier. |
| `location_id` | IntegerField | Must be at least 1. It is not a foreign key. |
| `max_temp_c` | FloatField | Maximum temperature. |
| `humidity_pct` | FloatField | Validated from 0 to 100. |
| `wind_speed_kmh` | FloatField | Validated as non-negative. |
| `rainfall_mm` | FloatField | Validated as non-negative. |
| `slope_angle_deg` | IntegerField | Validated from 0 to 90. |
| `vegetation_cover` | CharField(6) | One of `Low`, `Medium`, or `High`. |
| `landslide_observed` | nullable/blank CharField(3) | Historical recorded value `Yes` or `No`; the create form does not set it. |
| `landslide_prediction` | nullable/blank CharField(3) | Model-generated `Yes` or `No`. |
| `landslide_probability` | nullable FloatField | Model-generated probability, validated between 0 and 1. |
| `created_at` | DateTimeField | Automatically set when created. |

Model ordering is `-created_at`, then `-id`, so queries return newest records
first.

### `EmergencyAuthority`

`EmergencyAuthority.Meta.db_table` sets the exact table name `EmergencyAuthority`.

| Field | Django type | Meaning |
| --- | --- | --- |
| `id` | BigAutoField primary key | Automatically generated ID. |
| `authority_name` | CharField(200) | Authority display name. |
| `authority_type` | CharField(32) | Choice: disaster management, district administration, police, fire/rescue, other. |
| `location_id` | PositiveIntegerField, indexed | Authority's location identifier; not a foreign key. |
| `district` | CharField(100) | District label. |
| `email` | EmailField, blank allowed | Optional email address. |
| `phone_number` | CharField(32), blank allowed | Optional number. |
| `is_active` | BooleanField | Defaults to true. |
| `is_verified` | BooleanField | Defaults to false; help text says verify from an official source before enabling. |
| `created_at` | DateTimeField | Automatically set on creation. |
| `updated_at` | DateTimeField | Automatically updated on save. |

Rows are ordered by `authority_name`, then `id`. The response-agent currently
selects the first row in this order; it does not filter by `location_id`,
`is_active`, or `is_verified`.

## Relationships and non-persistent workflow data

- The two current application models have no foreign-key relationship.
- `location_id` is an integer in both models. No `Location` model exists.
- There is no current response-alert, email-attempt, or workflow-event model.
- Migrations 0003 and 0005 show that such alert/audit models existed in an
  intermediate migration history and were later removed. They must not be
  treated as current tables used by the app.
- The background agent's result is printed/logged; it is not stored in a
  current application table.
- Django also creates framework tables for auth, admin, sessions, and
  migrations; those are not custom observation-domain models.

## Example SQL queries

These are read queries for the current model tables. MySQL table-name
case-sensitivity depends on the MySQL host configuration; the authority table
is declared with the capitalized name shown.

```sql
-- Recent observations
SELECT id, location_id, max_temp_c, humidity_pct, wind_speed_kmh,
       rainfall_mm, slope_angle_deg, vegetation_cover,
       landslide_prediction, landslide_probability, created_at
FROM observations_landslideobservation
ORDER BY created_at DESC, id DESC;

-- Observations predicted as Yes
SELECT id, location_id, landslide_probability, created_at
FROM observations_landslideobservation
WHERE landslide_prediction = 'Yes'
ORDER BY created_at DESC;

-- Authorities, ordered the same way as the Python ORM selection
SELECT id, authority_name, authority_type, location_id, district,
       email, phone_number, is_active, is_verified
FROM EmergencyAuthority
ORDER BY authority_name, id;

-- Count outcomes
SELECT landslide_prediction, COUNT(*) AS observation_count
FROM observations_landslideobservation
GROUP BY landslide_prediction;
```

The application uses Django ORM for database reads and writes; the SQL above
is for understanding or read-only inspection. Avoid direct manual updates to
prediction columns because the API computes these fields.

## Migration history

- `0001_initial.py`: creates the first observation model.
- `0002_remove_landslideobservation_landslide_and_more.py`: renames the old
  outcome to `landslide_observed` and adds prediction/probability columns.
- `0003_emergencyauthority_landslideresponsealert_and_more.py`: adds
  authorities and intermediate alert/audit models.
- `0004_alter_emergencyauthority_table.py`: sets the authority table name.
- `0005_remove_landslideresponsealert_approved_by_and_more.py`: removes the
  intermediate alert/audit models and relations.

Always use migrations (`manage.py migrate`) rather than manually creating
tables. See [Backend Documentation](./Backend_Documentation.md) for API usage.
