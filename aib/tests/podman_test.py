import unittest
from unittest.mock import patch, call

from aib.podman import TemporaryContainer


class TestTemporaryContainer(unittest.TestCase):
    """Test the TemporaryContainer context manager."""

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_cleanup_enabled_by_default(self, mock_rm, mock_exists):
        """Test that cleanup is enabled by default."""
        mock_exists.return_value = True
        mock_rm.return_value = True

        with TemporaryContainer(None, "test-container") as container:
            self.assertEqual(container, "test-container")

        # Should have called cleanup
        mock_exists.assert_called_once_with(None, "test-container")
        mock_rm.assert_called_once_with(None, "test-container")

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_cleanup_explicit_true(self, mock_rm, mock_exists):
        """Test explicit cleanup=True."""
        mock_exists.return_value = True
        mock_rm.return_value = True

        with TemporaryContainer(None, "test-container", cleanup=True) as container:
            self.assertEqual(container, "test-container")

        # Should have called cleanup
        mock_exists.assert_called_once_with(None, "test-container")
        mock_rm.assert_called_once_with(None, "test-container")

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_cleanup_disabled(self, mock_rm, mock_exists):
        """Test that cleanup can be disabled."""
        with TemporaryContainer(None, "test-container", cleanup=False) as container:
            self.assertEqual(container, "test-container")

        # Should NOT have called cleanup
        mock_exists.assert_not_called()
        mock_rm.assert_not_called()

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_cleanup_on_exception(self, mock_rm, mock_exists):
        """Test that cleanup happens even when exception is raised."""
        mock_exists.return_value = True
        mock_rm.return_value = True

        with self.assertRaises(ValueError):
            with TemporaryContainer(None, "test-container") as container:
                self.assertEqual(container, "test-container")
                raise ValueError("Test exception")

        # Should still have called cleanup
        mock_exists.assert_called_once_with(None, "test-container")
        mock_rm.assert_called_once_with(None, "test-container")

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_no_cleanup_if_disabled_even_on_exception(self, mock_rm, mock_exists):
        """Test that cleanup=False prevents cleanup even on exceptions."""
        with self.assertRaises(ValueError):
            with TemporaryContainer(None, "test-container", cleanup=False):
                raise ValueError("Test exception")

        # Should NOT have called cleanup
        mock_exists.assert_not_called()
        mock_rm.assert_not_called()

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_cleanup_when_container_does_not_exist(self, mock_rm, mock_exists):
        """Test cleanup when container doesn't exist (idempotent)."""
        mock_exists.return_value = False

        with TemporaryContainer(None, "test-container"):
            pass

        # Should check existence but not attempt removal
        mock_exists.assert_called_once_with(None, "test-container")
        mock_rm.assert_not_called()

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    @patch("aib.podman.log")
    def test_cleanup_failure_is_logged(self, mock_log, mock_rm, mock_exists):
        """Test that cleanup failures are logged but don't raise."""
        mock_exists.return_value = True
        mock_rm.side_effect = Exception("Cleanup failed")

        # Should not raise exception
        with TemporaryContainer(None, "test-container"):
            pass

        # Should have logged the warning
        mock_log.warning.assert_called_once()
        self.assertIn("Failed to remove", str(mock_log.warning.call_args))

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_manual_cleanup_is_idempotent(self, mock_rm, mock_exists):
        """Test that manual cleanup can be called multiple times safely."""
        mock_exists.return_value = True
        mock_rm.return_value = True

        temp = TemporaryContainer(None, "test-container")
        temp.cleanup()
        temp.cleanup()  # Second call should be safe

        # Should only remove once (idempotent)
        mock_exists.assert_called_once_with(None, "test-container")
        mock_rm.assert_called_once_with(None, "test-container")

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_string_representation(self, mock_rm, mock_exists):
        """Test __str__ returns the container name."""
        temp = TemporaryContainer(None, "my-container")
        self.assertEqual(str(temp), "my-container")

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_context_manager_returns_name(self, mock_rm, mock_exists):
        """Test that entering context returns the container name."""
        mock_exists.return_value = True
        mock_rm.return_value = True

        with TemporaryContainer(None, "test-name") as name:
            self.assertEqual(name, "test-name")
            self.assertIsInstance(name, str)

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_multiple_sequential_contexts(self, mock_rm, mock_exists):
        """Test multiple sequential uses with different containers."""
        mock_exists.return_value = True
        mock_rm.return_value = True

        with TemporaryContainer(None, "container-1") as c1:
            self.assertEqual(c1, "container-1")

        with TemporaryContainer(None, "container-2") as c2:
            self.assertEqual(c2, "container-2")

        # Should have cleaned up both
        self.assertEqual(mock_exists.call_count, 2)
        self.assertEqual(mock_rm.call_count, 2)
        mock_exists.assert_has_calls(
            [call(None, "container-1"), call(None, "container-2")]
        )

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_nested_contexts(self, mock_rm, mock_exists):
        """Test nested TemporaryContainer contexts."""
        mock_exists.return_value = True
        mock_rm.return_value = True

        with TemporaryContainer(None, "outer") as outer:
            self.assertEqual(outer, "outer")
            with TemporaryContainer(None, "inner") as inner:
                self.assertEqual(inner, "inner")
            # Inner should be cleaned up here
            mock_rm.assert_called_with(None, "inner")

        # Outer should be cleaned up here
        self.assertEqual(mock_rm.call_count, 2)

    @patch("aib.podman.podman_image_exists")
    @patch("aib.podman.podman_image_rm")
    def test_dynamic_cleanup_decision(self, mock_rm, mock_exists):
        """Test that cleanup parameter can be determined dynamically."""
        mock_exists.return_value = True
        mock_rm.return_value = True

        # Test with True
        should_cleanup = True
        with TemporaryContainer(None, "container-1", cleanup=should_cleanup):
            pass
        self.assertEqual(mock_rm.call_count, 1)

        # Reset mocks
        mock_rm.reset_mock()
        mock_exists.reset_mock()

        # Test with False
        should_cleanup = False
        with TemporaryContainer(None, "container-2", cleanup=should_cleanup):
            pass
        mock_rm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
