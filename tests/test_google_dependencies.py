"""Exercise the installed Google/Protobuf stack without cloud credentials."""
import unittest

import grpc
from google.cloud import speech_v1
from google.rpc import status_pb2
from grpc_status import rpc_status


class GoogleDependencyTests(unittest.TestCase):
    def test_speech_config_round_trips_with_installed_protobuf(self):
        config = speech_v1.RecognitionConfig(
            encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="en-US",
            enable_word_time_offsets=True,
        )
        restored = speech_v1.RecognitionConfig.deserialize(
            speech_v1.RecognitionConfig.serialize(config)
        )
        self.assertEqual(restored, config)
        self.assertEqual(restored.language_code, "en-US")

    def test_grpc_status_serializes_google_rpc_details(self):
        original = status_pb2.Status(code=3, message="synthetic invalid argument")
        status = rpc_status.to_status(original)
        self.assertEqual(status.code, grpc.StatusCode.INVALID_ARGUMENT)
        payload = dict(status.trailing_metadata)["grpc-status-details-bin"]
        self.assertEqual(status_pb2.Status.FromString(payload), original)


if __name__ == "__main__":
    unittest.main()
