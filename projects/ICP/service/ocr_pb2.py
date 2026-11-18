# -*- coding: utf-8 -*-
# Message classes generated from the ocr.proto file descriptor.
# Regenerate with: python -m grpc_tools.protoc -I. --python_out=. ocr.proto
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf.internal import builder as _builder

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\tocr.proto\x12\x03icp"I\n\x0bCardRequest\x12\x0f\n\x07card_id\x18\x01 \x01(\t\x12\r\n\x05image\x18\x02 \x01(\x0c\x12\x1a\n\x12include_detections\x18\x03 \x01(\x08"I\n\nAssertions\x12\n\n\x02a1\x18\x01 \x01(\x08\x12\n\n\x02a2\x18\x02 \x01(\x08\x12\n\n\x02a3\x18\x03 \x01(\x08\x12\n\n\x02a4\x18\x04 \x01(\x08\x12\x0b\n\x03all\x18\x05 \x01(\x08"S\n\x06Timing\x12\x10\n\x08queue_ms\x18\x01 \x01(\x02\x12\x15\n\rpreprocess_ms\x18\x02 \x01(\x02\x12\x0e\n\x06ocr_ms\x18\x03 \x01(\x02\x12\x10\n\x08total_ms\x18\x04 \x01(\x02"\xfd\x01\n\x0cCardResponse\x12\x0f\n\x07card_id\x18\x01 \x01(\t\x12-\n\x06fields\x18\x02 \x03(\x0b2\x1d.icp.CardResponse.FieldsEntry\x12#\n\nassertions\x18\x03 \x01(\x0b2\x0f.icp.Assertions\x12\x1b\n\x06timing\x18\x04 \x01(\x0b2\x0b.icp.Timing\x12\x0f\n\x07variant\x18\x05 \x01(\t\x12\x12\n\nbatch_size\x18\x06 \x01(\x05\x12\x17\n\x0fdetections_json\x18\x07 \x01(\t\x1a-\n\x0bFieldsEntry\x12\x0b\n\x03key\x18\x01 \x01(\t\x12\r\n\x05value\x18\x02 \x01(\t:\x028\x0125\n\x03OCR\x12.\n\x07Extract\x12\x10.icp.CardRequest\x1a\x11.icp.CardResponseb\x06proto3')
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "ocr_pb2", globals())
