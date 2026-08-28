from . import models


def post_init_action(env):
    """Post-installation hook for car_park_permit module"""
    # These are implemented as SQL unique indexes to keep behavior consistent.
    cr = env.cr

    # x_car_model.x_name unique
    cr.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS x_car_model_name_uniq
        ON x_car_model (x_name)
    """)

    # x_car_color.x_name unique
    cr.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS x_car_color_name_uniq
        ON x_car_color (x_name)
    """)

    # x_car_park_request plate number unique for non-cancelled records
    cr.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS x_car_park_request_plate_uniq_active
        ON x_car_park_request (x_plate_number)
        WHERE x_state != 'cancelled'
    """)


def uninstall_action(env):
    """Uninstallation hook for car_park_permit module"""
    cr = env.cr
    cr.execute("DROP INDEX IF EXISTS x_car_park_request_plate_uniq_active")
    cr.execute("DROP INDEX IF EXISTS x_car_color_name_uniq")
    cr.execute("DROP INDEX IF EXISTS x_car_model_name_uniq")