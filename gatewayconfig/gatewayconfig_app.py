import sentry_sdk
import threading

# Attempt to load GPIO libraries, if there is a failure, fallback to mocks.
# The mocks are only intended to be used by test code.
try:
    # checks if you have access to RPi.GPIO, which is available inside RPi
    import RPi.GPIO as GPIO
    from gpiozero import Button, LED

except:
    # In case of exception, you are executing your script outside of RPi, so import Mock.GPIO
    import Mock.GPIO as GPIO

    # Also mock gpiozero pins
    from gpiozero import Device
    from gpiozero.pins.mock import MockFactory
    Device.pin_factory = MockFactory()

from hm_hardware_defs.variant import variant_definitions

from gatewayconfig.logger import logger
from gatewayconfig.processors.bluetooth_services_processor import BluetoothServicesProcessor
from gatewayconfig.processors.led_processor import LEDProcessor
from gatewayconfig.processors.diagnostics_processor import DiagnosticsProcessor
from gatewayconfig.processors.wifi_processor import WifiProcessor
from gatewayconfig.processors.bluetooth_advertisement_processor import BluetoothAdvertisementProcessor
from gatewayconfig.gatewayconfig_shared_state import GatewayconfigSharedState
from gatewayconfig.file_loader import read_eth0_mac_address, read_wlan0_mac_address, read_miner_keys
import gatewayconfig.nmcli_custom as nmcli_custom

USER_BUTTON_HOLD_SECONDS = 2

class GatewayconfigApp:
    def __init__(self, sentry_dsn, balena_app_name, balena_device_uuid, variant, eth0_mac_address_filepath, wlan0_mac_address_filepath,
        miner_keys_filepath, diagnostics_json_url, ethernet_is_online_filepath, firmware_version, is_gpio_enabled):

        self.variant = variant
        self.variant_details = variant_definitions[variant]
        self.init_sentry(sentry_dsn, balena_app_name, balena_device_uuid, variant)
        self.shared_state = GatewayconfigSharedState()
        self.init_nmcli()
        self.init_gpio(is_gpio_enabled)

        eth0_mac_address = read_eth0_mac_address(eth0_mac_address_filepath)
        wlan0_mac_address = read_wlan0_mac_address(wlan0_mac_address_filepath)
        logger.debug("Read eth0 mac address %s and wlan0 %s" % (eth0_mac_address, wlan0_mac_address))
        pub_key, onboarding_key, animal_name = read_miner_keys(miner_keys_filepath)
        logger.debug("Read onboarding pub_key: %s + animal_name: %s" % (pub_key, animal_name))

        self.bluetooth_services_processor = BluetoothServicesProcessor(eth0_mac_address, wlan0_mac_address, onboarding_key, pub_key, firmware_version, ethernet_is_online_filepath, self.shared_state)
        self.led_processor = LEDProcessor(self.status_led, self.shared_state, self.is_gpio_enabled)
        self.diagnostics_processor = DiagnosticsProcessor(diagnostics_json_url, self.shared_state)
        self.wifi_processor = WifiProcessor(self.shared_state)
        self.bluetooth_advertisement_processor = BluetoothAdvertisementProcessor(eth0_mac_address, self.shared_state, self.variant_details)
        
    def start(self):
        logger.debug("Starting ConfigApp")
        try:
            self.start_threads()

        except KeyboardInterrupt:
            logger.debug("KEYBOAD INTERRUPTION")
            self.stop()

        except Exception:
            logger.exception('GatewayConfigApp failed for unknown reason')
            self.stop()

    def stop(self):
        logger.debug("Stopping ConfigApp")
        GPIO.cleanup()
        # Quits the cputemp application
        self.bluetooth_services_processor.quit()

    def init_sentry(self, sentry_dsn, balena_app_name, balena_device_uuid, variant):
        sentry_sdk.init(sentry_dsn, environment=balena_app_name)
        sentry_sdk.set_user({ "id": balena_device_uuid })
        sentry_sdk.set_context("variant", { variant })

    def init_nmcli(self):
        nmcli_custom.disable_use_sudo()

    def init_gpio(self, is_gpio_enabled):
        self.is_gpio_enabled = is_gpio_enabled

        if is_gpio_enabled:
            self.user_button = Button(self.get_button_pin(), hold_time=USER_BUTTON_HOLD_SECONDS)
            self.user_button.when_held= self.start_bluetooth_advertisement
            self.status_led = LED(self.get_status_led_pin())
        else:
            self.user_button = None
            self.status_led = None

    # Use daemon threads so that everything exists cleanly when the program stops
    def start_threads(self):
        self.bluetooth_services_thread = threading.Thread(target=self.bluetooth_services_processor.run)
        self.led_thread = threading.Thread(target=self.led_processor.run)
        self.diagnostics_thread = threading.Thread(target=self.diagnostics_processor.run)
        self.wifi_thread = threading.Thread(target=self.wifi_processor.run)
        self.bluetooth_advertisement_thread = threading.Thread(target=self.bluetooth_advertisement_processor.run)

        self.led_thread.daemon = True
        self.led_thread.start()

        # self.bluetooth_services_thread.daemon = True
        self.bluetooth_services_thread.start()

        # self.diagnostics_thread.daemon = True
        self.diagnostics_thread.start()

        # self.wifi_thread.daemon = True
        self.wifi_thread.start()

        # self.bluetooth_advertisement_thread.daemon = True
        self.bluetooth_advertisement_thread.start()

    def start_bluetooth_advertisement(self):
        logger.debug("Starting bluetooth advertisement")
        self.shared_state.should_advertise_bluetooth = True

    def get_button_pin(self):
        return self.variant_details['BUTTON']

    def get_status_led_pin(self):
        return self.variant_details['STATUS']