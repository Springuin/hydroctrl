#!/usr/bin/env python3

import settings
import smbus
from statistics import mean, pstdev
from temperature import TemperatureInterface


class PHTheory:
    """
    A set of pH electrode functions.

    Functions are derived from the following equation:
    V = Voffset - slope * R * T * LN10 / F * (pH - 7)
    Voffset = V_pH7 + V_ADC_Offset
    """

    @staticmethod
    def ideal_slope(temp):
        """Slope of the ideal pH electrode, in V/pH"""

        # To be sure value is valid
        if temp < 0 or temp > 100:
            raise Exception('Temperature is out of range')

        # Properties of this Universe
        gas_const = 8.3144
        faraday_const = 96485
        abs_zero_temp = -273.15
        ln_10 = 2.3026

        return gas_const * (temp - abs_zero_temp) * ln_10 / faraday_const

    @staticmethod
    def compute_slope(temp, ph1, v1, ph2, v2):
        """Relative slope of the pH electrode. Equals 1 for the ideal electrode."""
        return (v1 - v2) / (ph2 - ph1) / PHTheory.ideal_slope(temp)

    @staticmethod
    def compute_offset(temp, slope, ph, v):
        """Offset voltage"""
        return v + slope * PHTheory.ideal_slope(temp) * (ph - 7)

    @staticmethod
    def compute_ph(temp, offset, slope, v):
        return 7 + (offset - v) / (slope * PHTheory.ideal_slope(temp))


class PHCalibration:
    """
    Parse calibration data.
    """

    # Acceptable electrode properties (compared to ideal electrode)
    max_slope_drift = 0.2
    max_v_ph7_drift = 30e-3

    def __init__(self):
        if len(settings.PH_CALIBRATION['points']) != 2:
            raise Exception('Only two point calibration is supported')

        point1 = settings.PH_CALIBRATION['points'][0]
        point2 = settings.PH_CALIBRATION['points'][1]
        temp = settings.PH_CALIBRATION['temperature']

        self.slope = PHTheory.compute_slope(
            temp,
            point1['ph'], point1['voltage'],
            point2['ph'], point2['voltage'])

        self.offset = PHTheory.compute_offset(
            temp, self.slope,
            point1['ph'], point1['voltage'])

        # Check slope
        if abs(self.slope - 1) > self.max_slope_drift:
            raise Exception('Electrode slope %.2f is out of range, replace the electrode' % self.slope)

        # Check offset
        v_ph7 = self.offset - settings.PH_ADC_V_OFFSET
        if abs(v_ph7) > self.max_v_ph7_drift:
            raise Exception('Electrode offset %.0f mV is out of range, replace the electrode' % (v_ph7 * 1e3))

        print('pH electrode status: slope %.2f, offset %.0f mV' % (self.slope, v_ph7 * 1e3))

    def compute_ph(self, temp, v):
        return PHTheory.compute_ph(temp, self.offset, self.slope, v)


class ADCInterface:
    """
    MCP3221 interface.
    """

    adc_bits = 12

    # Noise filtering
    filter_samples = 256

    def value_to_voltage(self, value):
        return float(value) * settings.PH_ADC_V_REF / (1 << self.adc_bits)

    def __init__(self):
        self.i2c = smbus.SMBus(settings.PH_ADC_I2C_BUSN)

    def _get_value(self):
        reading = self.i2c.read_i2c_block_data(settings.PH_ADC_I2C_ADDR, 0x00, 2)
        return (reading[0] << 8) + reading[1]

    def _get_values(self):
        values = []
        for n in range(0, self.filter_samples):
            values.append(self._get_value())
        return values

    def get_value(self):
        values = self._get_values()
        return mean(values)

    def get_voltage(self):
        value = self.get_value()
        return self.value_to_voltage(value)

    def get_value_with_stat(self):
        values = self._get_values()
        return {'value': mean(values), 'value_dev': pstdev(values)}

    def get_voltage_with_stat(self):
        data = self.get_value_with_stat()
        data['voltage'] = self.value_to_voltage(data['value'])
        data['voltage_dev'] = self.value_to_voltage(data['value_dev'])
        return data


class PHInterface:
    """
    Complete pH electrode interface with
    calibration and temperature compensation.
    """

    def __init__(self):
        self.adc = ADCInterface()
        self.calibration = PHCalibration()

    def get_ph(self, temp):
        voltage = self.adc.get_voltage()
        return self.calibration.compute_ph(temp, voltage)

    def get_ph_with_stat(self, temp):
        data = self.adc.get_voltage_with_stat()
        data['ph'] = self.calibration.compute_ph(temp, data['voltage'])
        data['ph_dev'] = data['voltage_dev'] / PHTheory.ideal_slope(temp)
        return data


def main():
    temperature = TemperatureInterface()
    ph = PHInterface()
    while True:
        try:
            temp = temperature.get_temperature()
            data = ph.get_ph_with_stat(temp)
            print('%.1fC  %.3fV +- %2.0fmV  %.2fpH +- %.2fpH' %
                  (temp, data['voltage'], data['voltage_dev'] * 1e3, data['ph'], data['ph_dev']))
        except Exception as e:
            print(e)


if __name__ == '__main__':
    main()
