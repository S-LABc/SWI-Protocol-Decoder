##
## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2019-2020 Philip Ã…kesson <philip.akesson@gmail.com>
## Edited 2021 Sklyar Roman <romansklyar15@gmail.com> <https://github.com/S-LABc>
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, see <http://www.gnu.org/licenses/>.
##

from common.srdhelper import bitpack
import sigrokdecode as srd

class SamplerateError(Exception):
    pass

class Pin:
    SWI, = range(1)

class Ann:
    BREAK, BREAK_RECOVERY, WAIT, BIT, STOP, BYTE, CHAR, = range(7)

class Decoder(srd.Decoder):
    api_version = 3
    id = 'swi'
    name = 'SWI'
    longname = 'Apple Single Wire Interface'
    desc = 'Used by Apple in Lightning and MagSafe.'
    license = 'gplv2+'
    inputs = ['logic']
    outputs = []
    tags = ['Embedded/industrial']
    channels = (
        {'id': 'swi', 'name': 'SWI', 'desc': 'Data line'},
    )
    options = (
        {'id': 'bitrate', 'desc': 'Bitrate', 'default': 98425},
    )
    annotations = (
        ('ascii', 'ASCII'),
        ('byte', 'Byte'),
        ('bit', 'Bit'),
        ('raw', 'Raw'),
        ('b', 'Break'),
        ('br', 'Break Recovery'),
        ('s', 'Stop'),
        ('w', 'Wait'),
    )
    annotation_rows = (
        ('ascii', 'ASCII', (Ann.CHAR,)),
        ('bytes', 'Bytes', (Ann.BYTE,)),
        ('raw', 'Raw', (Ann.BREAK, Ann.BREAK_RECOVERY, Ann.WAIT, Ann.BIT, Ann.STOP)),
    )

    def __init__(self):
        self.reset()

    def reset(self):
        self.samplerate = None
        self.startsample = 0
        self.bits = []
        self.bytepos = 0
        self.break_num = 1

    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)

    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value

    def put_bit(self, data):
        self.put(self.startsample, self.startsample + int(self.bit_width), self.out_ann, data)

    def handle_bit(self, bit):
        # Дабивить бит в массив для сборки байта
        self.bits.append(bit)
        # Вывести значение бита (1 или 0)
        self.put(self.startsample,
            self.startsample + int(self.bit_width),
            self.out_ann,
            [Ann.BIT, ['Bit: {:d}'.format(bit), '{:d}'.format(bit)]])
        # Если накопилось восемь битов
        if len(self.bits) == 8:
            # Собрать биты в байт
            current_byte = bitpack(self.bits)
            # Вывести значение байта (например 0x45)
            self.handle_byte(current_byte)
            # Вывести символ ASCII этого байта (например E)
            self.handle_char(current_byte)
            # Очистить битовый массив
            self.bits = []
            # Сбрость позицию байта
            self.bytepos = 0
            # Вывести сигнал STOP после каждокого байта
            self.startsample = self.samplenum + int(self.bit_width * 0.3)
            self.put(self.startsample,
                self.startsample + int(self.bit_width * 1.3),
                self.out_ann,
                [Ann.STOP, ['Stop', 'S']])
            
    def handle_byte(self, byte):
        self.put(self.bytepos,
            self.startsample + int(self.bit_width),
            self.out_ann,
            [Ann.BYTE, ['Byte: 0x{:02x}'.format(byte), '0x{:02x}'.format(byte)]])
        
    def handle_char(self, byte):
        self.put(self.bytepos,
            self.startsample + int(self.bit_width),
            self.out_ann,
            [Ann.CHAR, ['Char: {:c}'.format(byte), '{:c}'.format(byte)]])

    def handle_break(self):
        self.put(self.startsample,
            self.samplenum,
            self.out_ann,
            [Ann.BREAK, ['Break', 'B']])
        self.startsample = self.samplenum
        # После BREAK сразу добавляется BREAK_RECOVERY
        self.put(self.startsample,
            self.startsample + int(self.bit_width * 0.45),
            self.out_ann,
            [Ann.BREAK_RECOVERY, ['Break Recovery', 'BR']])
        self.startsample = self.samplenum
        # Если это завершающий BREAK
        if self.break_num == 2:
            self.break_num = 1
            # После BREAK_RECOVERY сразу добавляется WAIT
            self.put(self.startsample + int(self.bit_width * 0.45),
                self.startsample + int(self.bit_width * 2.0),
                self.out_ann,
                [Ann.WAIT, ['Wait', 'W']])
            self.startsample = self.samplenum
        else:
            self.break_num += 1
        self.bits = []
        self.bytepos = 0
        
    def decode(self):
        if not self.samplerate:
            raise SamplerateError('Cannot decode without samplerate.')
        self.bit_width = float(self.samplerate) / float(self.options['bitrate'])
        self.half_bit_width = self.bit_width / 2.0
        # Если низкий уровень на линии дольше этого значения, то это BREAK
        break_threshold = self.bit_width * 1.2
        # Ожидание появления высокого уровня на линии данных
        swi, = self.wait({Pin.SWI: 'h'})
        while True:
            # Вычисление длительности низкого уровня на линии SWI
            # f - нисходящий фронт
            # r - восходящий фронт
            swi, = self.wait({Pin.SWI: 'f'})
            self.startsample = self.samplenum
            if self.bytepos == 0:
                self.bytepos = self.samplenum
            swi, = self.wait({Pin.SWI: 'r'})
            # Проверка на состояние BREAK, Бит 0, Бит 1
            delta = self.samplenum - self.startsample
            if delta > break_threshold:
                self.handle_break()
            elif delta > self.half_bit_width:
                self.handle_bit(0)
            else:
                self.handle_bit(1)