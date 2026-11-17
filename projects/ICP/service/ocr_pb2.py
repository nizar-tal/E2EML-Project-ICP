# -*- coding: utf-8 -*-
# Protocol buffer compiler output. DO NOT EDIT!
# NO CHECKED-IN PROTOBUF GENCODE
# source: ocr.proto
# Protobuf Python Version: 7.35.1
"""Protocol buffer message classes for ocr.proto."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import runtime_version as _runtime_version
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC,
    7,
    35,
    1,
    '',
    'ocr.proto'
)
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\tocr.proto\x12\x03icp\"-\n\x0b\x43\x61rdRequest\x12\x0f\n\x07\x63\x61rd_id\x18\x01 \x01(\t\x12\r\n\x05image\x18\x02 \x01(\x0c\"I\n\nAssertions\x12\n\n\x02\x61\x31\x18\x01 \x01(\x08\x12\n\n\x02\x61\x32\x18\x02 \x01(\x08\x12\n\n\x02\x61\x33\x18\x03 \x01(\x08\x12\n\n\x02\x61\x34\x18\x04 \x01(\x08\x12\x0b\n\x03\x61ll\x18\x05 \x01(\x08\"S\n\x06Timing\x12\x10\n\x08queue_ms\x18\x01 \x01(\x02\x12\x15\n\rpreprocess_ms\x18\x02 \x01(\x02\x12\x0e\n\x06ocr_ms\x18\x03 \x01(\x02\x12\x10\n\x08total_ms\x18\x04 \x01(\x02\"\xe4\x01\n\x0c\x43\x61rdResponse\x12\x0f\n\x07\x63\x61rd_id\x18\x01 \x01(\t\x12-\n\x06\x66ields\x18\x02 \x03(\x0b\x32\x1d.icp.CardResponse.FieldsEntry\x12#\n\nassertions\x18\x03 \x01(\x0b\x32\x0f.icp.Assertions\x12\x1b\n\x06timing\x18\x04 \x01(\x0b\x32\x0b.icp.Timing\x12\x0f\n\x07variant\x18\x05 \x01(\t\x12\x12\n\nbatch_size\x18\x06 \x01(\x05\x1a-\n\x0b\x46ieldsEntry\x12\x0b\n\x03key\x18\x01 \x01(\t\x12\r\n\x05value\x18\x02 \x01(\t:\x02\x38\x01\x32\x35\n\x03OCR\x12.\n\x07\x45xtract\x12\x10.icp.CardRequest\x1a\x11.icp.CardResponseb\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'ocr_pb2', _globals)
if not _descriptor._USE_C_DESCRIPTORS:
  DESCRIPTOR._loaded_options = None
  _globals['_CARDRESPONSE_FIELDSENTRY']._loaded_options = None
  _globals['_CARDRESPONSE_FIELDSENTRY']._serialized_options = b'8\001'
  _globals['_CARDREQUEST']._serialized_start=18
  _globals['_CARDREQUEST']._serialized_end=63
  _globals['_ASSERTIONS']._serialized_start=65
  _globals['_ASSERTIONS']._serialized_end=138
  _globals['_TIMING']._serialized_start=140
  _globals['_TIMING']._serialized_end=223
  _globals['_CARDRESPONSE']._serialized_start=226
  _globals['_CARDRESPONSE']._serialized_end=454
  _globals['_CARDRESPONSE_FIELDSENTRY']._serialized_start=409
  _globals['_CARDRESPONSE_FIELDSENTRY']._serialized_end=454
  _globals['_OCR']._serialized_start=456
  _globals['_OCR']._serialized_end=509
# @@protoc_insertion_point(module_scope)
