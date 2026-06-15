INSERT INTO sensor_readings(greenhouse_id, sensor_id, metric, value, unit, measured_at)
SELECT
  'greenhouse_demo',
  metric_source.sensor_id,
  metric_source.metric,
  metric_source.base_value + ((extract(minute FROM measured_at)::integer / 5) % 12) * 0.3,
  metric_source.unit,
  measured_at
FROM generate_series(now() - interval '24 hours', now(), interval '5 minutes') measured_at
CROSS JOIN (
  VALUES
    ('sensor_temp_01', 'temperature_celsius', 22.4, 'celsius'),
    ('sensor_humidity_01', 'humidity_percent', 61.0, 'percent'),
    ('sensor_co2_01', 'co2_ppm', 790.0, 'ppm'),
    ('sensor_light_01', 'illuminance_lux', 17800.0, 'lux')
) AS metric_source(sensor_id, metric, base_value, unit);

INSERT INTO robot_state_history(robot_id, status, bed_id, battery_percent, recorded_at)
VALUES
  ('robot_demo_1', 'idle', 1, 87, now() - interval '15 minutes'),
  ('robot_demo_1', 'moving', 2, 86, now() - interval '10 minutes'),
  ('robot_demo_1', 'idle', 2, 86, now());

INSERT INTO schema_migrations(version)
VALUES ('002_seed_timeseries_data')
ON CONFLICT (version) DO NOTHING;
