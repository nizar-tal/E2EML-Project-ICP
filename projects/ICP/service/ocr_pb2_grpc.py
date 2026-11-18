# gRPC Python protocol compiler plugin output. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc
import warnings

import ocr_pb2 as ocr__pb2

GRPC_STUB_VERSION = '1.85.1'
GRPC_VERSION = grpc.__version__
_version_not_supported = False

try:
    from grpc._utilities import first_version_is_lower
    _version_not_supported = first_version_is_lower(GRPC_VERSION, GRPC_STUB_VERSION)
except ImportError:
    _version_not_supported = True

if _version_not_supported:
    raise RuntimeError(
        f'The grpc package installed is at version {GRPC_VERSION},'
        + ' but ocr_pb2_grpc.py depends on'
        + f' grpcio>={GRPC_STUB_VERSION}.'
        + f' Please upgrade your grpc module to grpcio>={GRPC_STUB_VERSION}'
        + f' or rebuild the stubs with grpcio-tools<={GRPC_VERSION}.'
    )


class OCRStub:
    """Missing associated documentation comment in .proto file."""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.Extract = channel.unary_unary(
                '/icp.OCR/Extract',
                request_serializer=ocr__pb2.CardRequest.SerializeToString,
                response_deserializer=ocr__pb2.CardResponse.FromString,
                _registered_method=True)


class OCRServicer:
    """Missing associated documentation comment in .proto file."""

    def Extract(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_OCRServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'Extract': grpc.unary_unary_rpc_method_handler(
                    servicer.Extract,
                    request_deserializer=ocr__pb2.CardRequest.FromString,
                    response_serializer=ocr__pb2.CardResponse.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'icp.OCR', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))
    server.add_registered_method_handlers('icp.OCR', rpc_method_handlers)



class OCR:
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def Extract(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(
            request,
            target,
            '/icp.OCR/Extract',
            ocr__pb2.CardRequest.SerializeToString,
            ocr__pb2.CardResponse.FromString,
            options,
            channel_credentials,
            insecure,
            call_credentials,
            compression,
            wait_for_ready,
            timeout,
            metadata,
            _registered_method=True)
