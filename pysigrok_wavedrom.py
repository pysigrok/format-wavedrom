"""PySigrok driver for wavedrom"""

__version__ = "0.0.2"

import io
from operator import itemgetter
import json

from sigrokdecode.output import Output

YELLOW = "3"
ORANGE = "4"
BLUE = "5"
CYAN = "6"
GREEN = "7"
PURPLE = "8"
RED = "9"

DEFAULT_COLORS = {
    "uart": {
        "tx-data":  YELLOW,
        "rx-data":  YELLOW,
        "tx-start": GREEN,
        "rx-start": GREEN,
        "tx-stop":  RED,
        "rx-stop":  RED,
    }
}

class WavedromOutput(Output):
    name = "wavedrom"
    desc = "wavedrom json"

    def __init__(self, openfile, driver, logic_channels=[], analog_channels=[], decoders=[]):
        self.logic_waves = []
        self.last_bit = []
        self.openfile = openfile
        driver_signals = [driver.name]
        self.signals = [driver_signals]
        for chan in logic_channels:
            wave = []
            self.logic_waves.append(wave)
            self.last_bit.append(None)
            driver_signals.append({"name": chan, "wave": wave})

        self.annotation_signals = {}
        self.annotation_rows = {}
        self.annotation_buffers = {}

        self.start_annotation = None
        self.end_annotation = None
        self.last_end = None

        self.previous_bits = None

    def _flush_annotations(self):
        for source in self.annotation_buffers:
            colors = DEFAULT_COLORS.get(source.id, {})
            for i, row in enumerate(self.annotation_rows[source]):
                signal = self.annotation_signals[source][i + 1]
                signal["wave"].append("x")
                if not row:
                    signal["wave"].extend(["."] * (self.end_annotation - self.start_annotation))
                    signal["wave"].append(".|")
                else:
                    next_start = row[0][0]
                    if next_start - self.start_annotation > 0:
                        signal["wave"].append("x")
                        signal["wave"].extend(["."] * (next_start - self.start_annotation - 1))
                    for j, entry in enumerate(row):
                        if j+1 < len(row):
                            next_start = row[j+1][0]
                        else:
                            next_start = self.end_annotation
                        start, end, data = entry
                        annotation_id, annotation_name = source.annotations[data[0]]
                        end = min(end, next_start)
                        signal["wave"].append(colors.get(annotation_id, "="))
                        signal["data"].append(data[1][0])
                        signal["wave"].extend(["."] * (end - start - 1))
                        xes = next_start - end
                        if xes > 0:
                            signal["wave"].append("x")
                            signal["wave"].extend(["."] * (xes - 1))
                    signal["wave"].append("x|")
                # print(signal)
                row.clear()
        self._output_bits(True, *self.previous_bits)
        self.last_end = self.end_annotation
        self.end_annotation = None
        self.start_annotation = None

    def _output_bits(self, pipe, startsample, endsample, data):
        startsample = max(self.start_annotation, startsample)
        endsample = min(self.end_annotation, endsample)
        for bit, var in enumerate(self.logic_waves):
            val = (data[1] & (1 << bit)) != 0
            if val == self.last_bit[bit]:
                var.append(".")
            else:
                var.append("1" if val else "0")
                self.last_bit[bit] = val
            var.extend(["."] * (endsample - startsample - 1))
            if pipe:
                var.append(".|")

    def output(self, source, startsample, endsample, data):
        ptype = data[0]
        if ptype == "logic":
            pipe = False
            # Delay bits by one call
            output_bits = self.previous_bits
            self.previous_bits = (startsample, endsample, data)
            if output_bits is None:
                return
                
            startsample, endsample, data = output_bits
            if self.end_annotation is not None and startsample > self.end_annotation:
                self._flush_annotations()
                return
            elif self.last_end is not None and startsample < self.last_end:
                # Fall through and output this bit.
                endsample = min(endsample, self.last_end)
                pipe = True
                pass
            elif self.end_annotation is None:
                return
            self._output_bits(pipe, *output_bits)

        elif ptype == "analog":
            pass
        else:
            # annotation
            if self.end_annotation is None:
                self.start_annotation = startsample
                self.end_annotation = endsample
            self.end_annotation = max(self.end_annotation, endsample)

            if source not in self.annotation_signals:
                decoder_buffers = [None] * len(source.annotations)
                signal_group = [source.name]
                decoder_rows = []
                for row_id, label, annotations in source.annotation_rows:
                    row_var = {"name": label, "wave": [], "data": []}
                    buffer = []
                    decoder_rows.append(buffer)
                    for a in annotations:
                        decoder_buffers[a] = buffer
                    signal_group.append(row_var)
                self.signals.append(signal_group)
                self.annotation_buffers[source] = decoder_buffers
                self.annotation_rows[source] = decoder_rows
                self.annotation_signals[source] = signal_group

            buffer = self.annotation_buffers[source][data[0]]
            buffer.append((startsample, endsample, data))

    @staticmethod
    def _join_waves(signals):
        for i, signal in enumerate(signals):
            if isinstance(signal, dict):
                signal["wave"] = "".join(signal["wave"])
            elif isinstance(signal, list):
                WavedromOutput._join_waves(signal)
            elif i == 0 and isinstance(signal, str):
                # group name
                pass
            else:
                print(signal)
                raise RuntimeError("Unexpected signal type")


    def stop(self):
        if self.end_annotation is not None:
            self._flush_annotations()
        signals = WavedromOutput._join_waves(self.signals)
        json.dump({"signal": self.signals, "config": {"skin": "narrow"}, "foot": {"tock": 0}}, io.TextIOWrapper(self.openfile), indent=2)
