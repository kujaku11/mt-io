# -*- coding: utf-8 -*-
"""Pytest suite for LEMI417 reader and helpers using synthetic data."""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


# In developer environments where local mth5 is editable, importing mt_timeseries
# can trigger a circular import through mt_io.reader. A lightweight stub keeps
# these unit tests isolated from external package import side effects.
if "mth5" not in sys.modules:
    mth5_stub = types.ModuleType("mth5")
    mth5_utils_stub = types.ModuleType("mth5.utils")
    mth5_fdsn_stub = types.ModuleType("mth5.utils.fdsn_tools")
    mth5_utils_stub.fdsn_tools = mth5_fdsn_stub
    mth5_stub.utils = mth5_utils_stub
    sys.modules["mth5"] = mth5_stub
    sys.modules["mth5.utils"] = mth5_utils_stub
    sys.modules["mth5.utils.fdsn_tools"] = mth5_fdsn_stub

from mt_io.lemi import LEMI417, read_lemi417


def _to_bcd(value: int) -> int:
    """Encode integer [0, 99] into one BCD byte."""
    if not 0 <= value <= 99:
        raise ValueError("BCD helper only supports values in [0, 99]")
    return ((value // 10) << 4) | (value % 10)


def _build_tag(start_time: datetime, fs_value: int = 4) -> bytes:
    """Build a 32-byte LEMI417 block tag for synthetic tests."""
    tag = bytearray(32)
    tag[0:4] = b"417A"
    tag[4] = _to_bcd(12)  # serial number

    # Date/time in BCD
    tag[5] = _to_bcd(start_time.year - 2000)
    tag[6] = _to_bcd(start_time.month)
    tag[7] = _to_bcd(start_time.day)
    tag[8] = _to_bcd(start_time.hour)
    tag[9] = _to_bcd(start_time.minute)
    tag[10] = _to_bcd(start_time.second)

    # Latitude: 34 + 30.00/60 = 34.5 (N)
    tag[11] = _to_bcd(34)
    tag[12] = _to_bcd(30)
    tag[13] = _to_bcd(0)
    tag[14] = _to_bcd(0)
    tag[15] = ord("N")

    # Longitude: 1*100 + 7 + 15.00/60 = 107.25 (W)
    tag[16] = _to_bcd(1)
    tag[17] = _to_bcd(7)
    tag[18] = _to_bcd(15)
    tag[19] = _to_bcd(0)
    tag[20] = _to_bcd(0)
    tag[21] = ord("W")

    tag[23] = _to_bcd(1)
    tag[24] = _to_bcd(23)  # elevation: 1*1000 + 23*10 = 1230
    tag[25] = fs_value  # sample_rate = 4 / fs_value
    tag[26] = 127  # vin 12.7
    tag[27] = 123  # vbat 12.3
    tag[28:32] = bytes([10, 20, 30, 40])
    return bytes(tag)


def _build_data_segment() -> bytes:
    """Build a 480-byte data segment (16 samples x 30 bytes)."""
    segment = np.zeros((16, 30), dtype=np.uint8)

    # Sample 0, bx raw 24-bit = 100 -> 1.0 after int2float24
    bx_raw = 100
    segment[0, 0] = bx_raw & 0xFF
    segment[0, 1] = (bx_raw >> 8) & 0xFF
    segment[0, 2] = (bx_raw >> 16) & 0xFF

    # Sample 0, e1 raw 32-bit = 200 -> 2.0 after int2float32
    e1_raw = 200
    off = 9
    segment[0, off] = e1_raw & 0xFF
    segment[0, off + 1] = (e1_raw >> 8) & 0xFF
    segment[0, off + 2] = (e1_raw >> 16) & 0xFF
    segment[0, off + 3] = (e1_raw >> 24) & 0xFF

    # Sample 0, temp_h raw 300 -> 3.0 after int2float16
    t_raw = 300
    segment[0, 25] = t_raw & 0xFF
    segment[0, 26] = (t_raw >> 8) & 0xFF

    return segment.tobytes()


def _write_binary_file(
    path: Path,
    start_time: datetime,
    n_blocks: int = 1,
    fs_value: int = 4,
) -> Path:
    """Write a synthetic LEMI417 binary file with one or more blocks."""
    with open(path, "wb") as f:
        for i in range(n_blocks):
            block_start = start_time + timedelta(seconds=16 * i)
            f.write(_build_tag(block_start, fs_value=fs_value))
            f.write(_build_data_segment())
    return path


@pytest.fixture
def lemi417_file(tmp_path) -> Path:
    """Synthetic one-block LEMI417 file."""
    return _write_binary_file(
        tmp_path / "synthetic_417.bin",
        datetime(2026, 3, 4, 12, 30, 0),
        n_blocks=1,
        fs_value=4,
    )


@pytest.fixture
def loaded_lemi417(lemi417_file) -> LEMI417:
    """LEMI417 object with loaded synthetic data."""
    obj = LEMI417(lemi417_file)
    obj.read()
    return obj


class TestLEMI417Initialization:
    def test_init_defaults(self):
        obj = LEMI417()
        assert obj.fn is None
        assert obj.data is None
        assert obj.sample_rate is None
        assert np.array_equal(obj.conv_factors, np.ones(7))

    def test_init_with_missing_file_raises(self, tmp_path):
        with pytest.raises(IOError):
            LEMI417(tmp_path / "does_not_exist.bin")


class TestLEMI417Helpers:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (np.array([0x12, 0x34]), np.array([12, 34])),
            (0x59, 59),
        ],
    )
    def test_bcd_to_int(self, raw, expected):
        out = LEMI417._bcd_to_int(raw)
        if isinstance(expected, np.ndarray):
            assert np.array_equal(out, expected)
        else:
            assert out == expected

    @pytest.mark.parametrize(
        "method, positive, wrapped, expected_positive, expected_wrapped",
        [
            (LEMI417.int2float24, 100, 2**24 - 100, 1.0, -1.0),
            (LEMI417.int2float32, 100, 2**32 - 100, 1.0, -1.0),
            (LEMI417.int2float16, 100, 2**16 - 100, 1.0, -1.0),
        ],
    )
    def test_int_converters_scalar_and_array(
        self,
        method,
        positive,
        wrapped,
        expected_positive,
        expected_wrapped,
        subtests,
    ):
        scalar_out = method(positive)
        assert scalar_out == pytest.approx(expected_positive)

        arr_out = method(np.array([positive, wrapped]))
        with subtests.test(msg="array positive"):
            assert arr_out[0] == pytest.approx(expected_positive)
        with subtests.test(msg="array wrapped negative"):
            assert arr_out[1] == pytest.approx(expected_wrapped)

    @pytest.mark.parametrize(
        "position, expected",
        [
            (np.array([34, 30, 0, 0]), 34.5),
            (np.array([10, 0, 0, 0]), 10.0),
        ],
    )
    def test_latitude_position(self, position, expected):
        assert LEMI417.latitude_position(position) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "position, expected",
        [
            (np.array([1, 7, 15, 0, 0]), 107.25),
            (np.array([0, 8, 0, 0, 0]), 8.0),
        ],
    )
    def test_longitude_position(self, position, expected):
        assert LEMI417.longitude_position(position) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "hemisphere, expected",
        [("N", 1), ("E", 1), ("S", -1), ("W", -1), ("X", 1)],
    )
    def test_hemisphere_parser(self, hemisphere, expected):
        assert LEMI417.hemisphere_parser(hemisphere) == expected


class TestLEMI417Read:
    def test_read_requires_filename(self):
        with pytest.raises(ValueError, match="No input file specified"):
            LEMI417().read()

    def test_read_empty_file_raises(self, tmp_path):
        empty = tmp_path / "empty.bin"
        empty.write_bytes(b"")
        obj = LEMI417(empty)
        with pytest.raises(ValueError, match="contains no valid data blocks"):
            obj.read()

    def test_read_populates_data_and_metadata(self, loaded_lemi417):
        obj = loaded_lemi417

        assert obj.sample_rate == pytest.approx(1.0)
        assert obj.n_samples == 16
        assert obj.start == datetime(2026, 3, 4, 12, 30, 0)
        assert obj.end == datetime(2026, 3, 4, 12, 30, 15)

        assert list(obj.data.columns) == [
            "bx",
            "by",
            "bz",
            "e1",
            "e2",
            "e3",
            "e4",
            "temperature_h",
            "temperature_e",
        ]
        assert obj.data.iloc[0]["bx"] == pytest.approx(1.0)
        assert obj.data.iloc[0]["e1"] == pytest.approx(2.0)
        assert obj.data.iloc[0]["temperature_h"] == pytest.approx(3.0)

        assert obj.latitude == pytest.approx(34.5)
        assert obj.longitude == pytest.approx(-107.25)
        assert obj.elevation == pytest.approx(1230.0)

    def test_string_repr_without_data(self):
        s = str(LEMI417())
        assert "LEMI 417 data" in s
        assert "No data loaded" in s

    def test_string_repr_with_data(self, loaded_lemi417):
        s = str(loaded_lemi417)
        assert "start:" in s
        assert "N samples:" in s
        assert "latitude:" in s


class TestLEMI417AddAndMetadata:
    @staticmethod
    def _obj_with_data(
        start: datetime, n: int = 16, sample_rate: float = 1.0
    ) -> LEMI417:
        idx = pd.date_range(start=start, periods=n, freq="1s")
        data = pd.DataFrame(
            np.zeros((n, 9)),
            index=idx,
            columns=[
                "bx",
                "by",
                "bz",
                "e1",
                "e2",
                "e3",
                "e4",
                "temperature_h",
                "temperature_e",
            ],
        )
        obj = LEMI417()
        obj.data = data
        obj.sample_rate = sample_rate
        obj._start = idx[0].to_pydatetime()
        obj._end = idx[-1].to_pydatetime()
        obj.header_list = [
            {
                "latitude": 34.5,
                "longitude": -107.25,
                "elevation": 1230,
                "vin": 12.7,
            }
        ]
        return obj

    def test_add_requires_lemi417_instance(self):
        obj = self._obj_with_data(datetime(2026, 1, 1, 0, 0, 0))
        with pytest.raises(TypeError):
            _ = obj + "not_a_lemi"

    def test_add_requires_data(self):
        obj1 = LEMI417()
        obj2 = LEMI417()
        with pytest.raises(ValueError, match="must have data"):
            _ = obj1 + obj2

    def test_add_concatenates_continuous_times(self):
        start = datetime(2026, 1, 1, 0, 0, 0)
        obj1 = self._obj_with_data(start)
        obj2 = self._obj_with_data(start + timedelta(seconds=16))

        out = obj1 + obj2
        assert isinstance(out, LEMI417)
        assert out.n_samples == 32
        assert out.start == obj1.start
        assert out.end == obj2.end
        assert len(out.header_list) == 2

    def test_add_raises_on_large_gap(self):
        start = datetime(2026, 1, 1, 0, 0, 0)
        obj1 = self._obj_with_data(start)
        obj2 = self._obj_with_data(start + timedelta(seconds=40))

        with pytest.raises(ValueError, match="Time gap detected"):
            _ = obj1 + obj2

    def test_station_and_run_metadata(self):
        obj = self._obj_with_data(datetime(2026, 1, 1, 0, 0, 0))

        station = obj.station_metadata
        run = obj.run_metadata

        assert station.location.latitude == pytest.approx(34.5)
        assert station.location.longitude == pytest.approx(-107.25)
        assert run.data_logger.model == "LEMI417"
        assert run.sample_rate == pytest.approx(1.0)
        assert len(run.channels_recorded_auxiliary) == 2
        assert len(run.channels_recorded_electric) == 2
        assert len(run.channels_recorded_magnetic) == 3


class TestLEMI417CalibrationAndRunTS:
    def test_read_calibration(self, tmp_path):
        cal_file = tmp_path / "cal.json"
        cal_file.write_text(
            json.dumps(
                {
                    "Calibration": {
                        "gain": 2.0,
                        "Freq": [1.0, 10.0],
                        "Re": [3.0, 0.0],
                        "Im": [4.0, 1.0],
                    }
                }
            )
        )

        fap = LEMI417().read_calibration(cal_file)

        assert fap.gain == pytest.approx(2.0)
        assert np.array_equal(fap.frequencies, np.array([1.0, 10.0]))
        assert np.allclose(fap.amplitudes, np.array([5.0, 1.0]))
        assert np.allclose(
            fap.phases,
            np.array([np.arctan2(4.0, 3.0), np.arctan2(1.0, 0.0)]),
        )

    def test_to_run_ts_requires_data(self):
        with pytest.raises(ValueError, match="No data loaded"):
            LEMI417().to_run_ts()

    def test_to_run_ts_builds_channels(self, loaded_lemi417):
        run_ts = loaded_lemi417.to_run_ts(e_channels=["e1"])
        assert run_ts is not None
        assert len(run_ts.channels) == 6  # bx, by, bz, e1, temp_h, temp_e

    def test_to_run_ts_applies_calibration(self, loaded_lemi417, tmp_path):
        cal_file = tmp_path / "bx_cal.json"
        cal_file.write_text(
            json.dumps(
                {
                    "Calibration": {
                        "gain": 1.0,
                        "Freq": [1.0],
                        "Re": [1.0],
                        "Im": [0.0],
                    }
                }
            )
        )

        run_ts = loaded_lemi417.to_run_ts(calibration_dict={"bx": cal_file})
        bx_filters = run_ts.dataset.bx.attrs["filters"]
        assert bx_filters
        assert bx_filters[0]["applied_filter"]["name"] == "lemi417_bx_calibration"


class TestReadLemi417Factory:
    def test_read_lemi417_single_file(self, lemi417_file):
        run_ts = read_lemi417(lemi417_file)
        assert run_ts is not None
        assert len(run_ts.channels) == 7

    def test_read_lemi417_multiple_files(self, tmp_path):
        f1 = _write_binary_file(
            tmp_path / "part1.bin", datetime(2026, 3, 4, 12, 30, 0), n_blocks=1
        )
        f2 = _write_binary_file(
            tmp_path / "part2.bin", datetime(2026, 3, 4, 12, 30, 16), n_blocks=1
        )

        run_ts = read_lemi417([f1, f2])
        assert run_ts is not None
        assert run_ts.dataset.time.size == 32

    def test_read_lemi417_passes_args(self, lemi417_file):
        with patch.object(LEMI417, "to_run_ts") as mock_to_run_ts:
            mock_to_run_ts.return_value = "sentinel"
            out = read_lemi417(lemi417_file, e_channels=["e1"], calibration_dict={})

        assert out == "sentinel"
        mock_to_run_ts.assert_called_once_with(e_channels=["e1"], calibration_dict={})
