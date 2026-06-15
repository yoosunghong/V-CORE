INSERT INTO greenhouses(greenhouse_id, name, location)
VALUES ('greenhouse_demo', 'PAI Demo Greenhouse', 'Demo Zone')
ON CONFLICT (greenhouse_id) DO UPDATE
SET name = EXCLUDED.name,
    location = EXCLUDED.location;

INSERT INTO beds(bed_id, greenhouse_id, zone, crop, growth_stage, harvestable, robot_accessible)
VALUES
  (1, 'greenhouse_demo', 'A', 'lettuce', 'growing', false, true),
  (2, 'greenhouse_demo', 'A', 'lettuce', 'harvest_ready', true, true),
  (3, 'greenhouse_demo', 'B', 'basil', 'seedling', false, true),
  (4, 'greenhouse_demo', 'B', 'strawberry', 'harvest_ready', true, false)
ON CONFLICT (bed_id) DO UPDATE
SET zone = EXCLUDED.zone,
    crop = EXCLUDED.crop,
    growth_stage = EXCLUDED.growth_stage,
    harvestable = EXCLUDED.harvestable,
    robot_accessible = EXCLUDED.robot_accessible,
    updated_at = now();

INSERT INTO robots(robot_id, display_name, status, current_bed_id, battery_percent)
VALUES ('robot_demo_1', 'Demo Harvest Robot 1', 'idle', 1, 87)
ON CONFLICT (robot_id) DO UPDATE
SET display_name = EXCLUDED.display_name,
    status = EXCLUDED.status,
    current_bed_id = EXCLUDED.current_bed_id,
    battery_percent = EXCLUDED.battery_percent,
    updated_at = now();

INSERT INTO actuators(actuator_id, greenhouse_id, actuator_type, status)
VALUES
  ('fan_zone_a', 'greenhouse_demo', 'fan', 'auto'),
  ('light_zone_b', 'greenhouse_demo', 'light', 'on')
ON CONFLICT (actuator_id) DO UPDATE
SET actuator_type = EXCLUDED.actuator_type,
    status = EXCLUDED.status,
    updated_at = now();

INSERT INTO schema_migrations(version)
VALUES ('002_seed_domain_data')
ON CONFLICT (version) DO NOTHING;
