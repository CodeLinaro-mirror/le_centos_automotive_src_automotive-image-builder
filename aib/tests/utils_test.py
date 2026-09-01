import os
import tempfile
import unittest
from io import StringIO
from unittest.mock import Mock

from aib import utils


class TestExtractCommentsHeader(unittest.TestCase):
    def test_extract_comment_header(self):
        data = """# foo bar
        some other text
        """

        res = utils.extract_comment_header(StringIO(data))
        self.assertEqual(res, "foo bar")

        data = """# more
        # foobar
        some other text
        """

        res = utils.extract_comment_header(StringIO(data))
        self.assertEqual(res, "more\nfoobar")

        data = """# foo
        #  indented
        some other text
        """

        res = utils.extract_comment_header(StringIO(data))
        self.assertEqual(res, "foo\n indented")

        data = """#empty lines
        #
        #
        some other text
        """
        res = utils.extract_comment_header(StringIO(data))
        self.assertEqual(res, "empty lines")

    def test_extract_comment_header_edge_cases(self):
        """Test edge cases for extract_comment_header"""
        # Empty file
        data = ""
        res = utils.extract_comment_header(StringIO(data))
        self.assertEqual(res, "")

        # No comments
        data = "just regular text"
        res = utils.extract_comment_header(StringIO(data))
        self.assertEqual(res, "")

        # Comments with no indentation
        data = """#comment1
#comment2
regular text
"""
        res = utils.extract_comment_header(StringIO(data))
        self.assertEqual(res, "comment1\ncomment2")


class TestGetOsbuildMajorVersion(unittest.TestCase):
    def test_get_osbuild_major_version(self):
        """Test get_osbuild_major_version function"""
        mock_runner = Mock()
        mock_runner.run_as_user.return_value = "osbuild 1.7.5"

        result = utils.get_osbuild_major_version(mock_runner)

        self.assertEqual(result, 1)
        mock_runner.run_as_user.assert_called_once_with(
            ["/usr/bin/osbuild", "--version"],
            capture_output=True,
        )

    def test_get_osbuild_major_version_different_versions(self):
        """Test get_osbuild_major_version with different version formats"""
        mock_runner = Mock()

        # Test version 2.x
        mock_runner.run_as_user.return_value = "osbuild 2.4.0"
        result = utils.get_osbuild_major_version(mock_runner)
        self.assertEqual(result, 2)

        # Test version 3.x
        mock_runner.run_as_user.return_value = "osbuild 3.0.1"
        result = utils.get_osbuild_major_version(mock_runner)
        self.assertEqual(result, 3)


class TestCountTrailingZeros(unittest.TestCase):
    """Tests for count_trailing_zeros function."""

    def test_no_trailing_zeros(self):
        """Test with no trailing zeros."""
        self.assertEqual(utils.count_trailing_zeros(b"hello"), 0)
        self.assertEqual(utils.count_trailing_zeros(b"\x01\x02\x03"), 0)

    def test_all_zeros(self):
        """Test with all zeros."""
        self.assertEqual(utils.count_trailing_zeros(b"\x00\x00\x00"), 3)
        self.assertEqual(utils.count_trailing_zeros(b"\x00" * 100), 100)

    def test_some_trailing_zeros(self):
        """Test with some trailing zeros."""
        self.assertEqual(utils.count_trailing_zeros(b"hello\x00\x00\x00"), 3)
        self.assertEqual(utils.count_trailing_zeros(b"\x01\x02\x00"), 1)
        self.assertEqual(utils.count_trailing_zeros(b"data\x00" * 10), 1)

    def test_empty_bytes(self):
        """Test with empty bytes."""
        self.assertEqual(utils.count_trailing_zeros(b""), 0)

    def test_single_byte(self):
        """Test with single byte."""
        self.assertEqual(utils.count_trailing_zeros(b"\x00"), 1)
        self.assertEqual(utils.count_trailing_zeros(b"\x01"), 0)

    def test_zeros_in_middle(self):
        """Zeros in middle should not be counted."""
        self.assertEqual(utils.count_trailing_zeros(b"hello\x00\x00world"), 0)
        self.assertEqual(utils.count_trailing_zeros(b"\x00\x00\x01\x00\x00"), 2)


class TestRoundup(unittest.TestCase):
    """Tests for roundup function."""

    def test_already_aligned(self):
        """Test numbers already aligned to block size."""
        self.assertEqual(utils.roundup(512, 512), 512)
        self.assertEqual(utils.roundup(1024, 512), 1024)
        self.assertEqual(utils.roundup(0, 512), 0)

    def test_needs_rounding(self):
        """Test numbers that need rounding up."""
        self.assertEqual(utils.roundup(100, 512), 512)
        self.assertEqual(utils.roundup(513, 512), 1024)
        self.assertEqual(utils.roundup(1000, 512), 1024)
        self.assertEqual(utils.roundup(1, 512), 512)

    def test_different_block_sizes(self):
        """Test with various block sizes."""
        self.assertEqual(utils.roundup(100, 1), 100)
        self.assertEqual(utils.roundup(100, 10), 100)
        self.assertEqual(utils.roundup(101, 10), 110)
        self.assertEqual(utils.roundup(100, 4096), 4096)
        self.assertEqual(utils.roundup(4097, 4096), 8192)

    def test_zero_block_causes_error(self):
        """Test that zero block size causes division by zero."""
        # This exposes bug #2 - currently crashes instead of raising proper error
        with self.assertRaises(ZeroDivisionError):
            utils.roundup(100, 0)


class TestExtractPartOfFile(unittest.TestCase):
    """Tests for extract_part_of_file function."""

    def setUp(self):
        """Set up temporary directory for tests."""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_basic_extraction(self):
        """Test basic file extraction."""
        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.bin")

        with open(src, "wb") as f:
            f.write(b"hello world")

        written = utils.extract_part_of_file(src, dst, 0, 11)

        self.assertEqual(written, 11)
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"hello world")

    def test_extract_with_offset(self):
        """Test extraction starting at offset."""
        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.bin")

        with open(src, "wb") as f:
            f.write(b"prefix:data:suffix")

        # Extract just "data" (bytes 7-11)
        written = utils.extract_part_of_file(src, dst, 7, 4)

        self.assertEqual(written, 4)
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"data")

    def test_extract_with_chunking(self):
        """Test extraction with small chunk size."""
        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.bin")

        data = b"x" * 1000
        with open(src, "wb") as f:
            f.write(data)

        # Use small chunk size to test chunking
        written = utils.extract_part_of_file(src, dst, 0, 1000, chunk_size=100)

        self.assertEqual(written, 1000)
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), data)

    def test_extract_past_eof(self):
        """Test extraction when size extends past EOF."""
        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.bin")

        with open(src, "wb") as f:
            f.write(b"hello")

        # Request 100 bytes but file only has 5
        written = utils.extract_part_of_file(src, dst, 0, 100)

        # Should only write the actual data bytes
        self.assertEqual(written, 5)

        # File should be sized to requested size with hole at end
        self.assertEqual(os.path.getsize(dst), 100)

        with open(dst, "rb") as f:
            self.assertEqual(f.read(5), b"hello")
            # Rest should be zeros (from the hole)
            f.seek(5)
            self.assertEqual(f.read(95), b"\x00" * 95)

    def test_truncate_partition_size(self):
        """Test truncating trailing hole."""
        src = os.path.join(self.test_dir, "source.bin")

        # Data with trailing hole
        with open(src, "wb") as f:
            f.write(b"data")
            f.seek(604)
            f.write(b"")

        size = utils.truncate_partition_size(src, 0, 604, 512)

        self.assertEqual(size, 512)

    def test_truncate_partition_size_exact_block(self):
        """Test truncating when data is exactly block-aligned."""
        src = os.path.join(self.test_dir, "source.bin")

        # Exactly 512 bytes data + hole
        with open(src, "wb") as f:
            f.write(b"x" * 512)
            f.seek(1012)
            f.write(b"")

        size = utils.truncate_partition_size(src, 0, 1012, 512)

        self.assertEqual(size, 512)

    def test_truncate_partition_size_no_trailing_hole(self):
        """Test truncate when there's no trailing hole."""
        src = os.path.join(self.test_dir, "source.bin")

        with open(src, "wb") as f:
            f.write(b"x" * 1024)

        size = utils.truncate_partition_size(src, 0, 1024, 512)

        self.assertEqual(size, 1024)

    def test_truncate_partition_size_entirely_sparse(self):
        """Test truncate when partition is entirely sparse."""
        src = os.path.join(self.test_dir, "source.bin")

        with open(src, "wb") as f:
            f.seek(1024)
            f.write(b"")

        size = utils.truncate_partition_size(src, 0, 1024, 512)

        self.assertEqual(size, 0)

    def test_truncate_partition_size_with_offset(self):
        """Test truncate with non-zero start offset."""
        src = os.path.join(self.test_dir, "source.bin")

        with open(src, "wb") as f:
            f.write(b"x" * 1000)
            f.write(b"y" * 500)
            f.seek(2000)
            f.write(b"")

        size = utils.truncate_partition_size(src, 1000, 1000, 512)

        self.assertEqual(size, 512)

    def _create_sparse_file(self, path, *regions):
        """Helper to create sparse files with actual holes.

        regions: tuples of (offset, data) where data is written at offset.
        Gaps between regions become sparse holes.
        """
        with open(path, "wb") as f:
            for offset, data in regions:
                f.seek(offset)
                f.write(data)
            # Use truncate via os.ftruncate to create sparse file
            fd = f.fileno()
            if regions:
                max_offset = max(offset + len(data) for offset, data in regions)
                os.ftruncate(fd, max_offset)

    def test_extract_sparse_file(self):
        """Test extracting sparse file preserves holes."""
        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.bin")

        # Create sparse file: data at 0, hole, data at 1MB
        self._create_sparse_file(src, (0, b"start"), (1024 * 1024, b"end"))

        written = utils.extract_part_of_file(src, dst, 0, 1024 * 1024 + 3)

        # Should write data regions (rounded to block boundaries by filesystem)
        # First region: 0-4095 (block-aligned), second region: 1048576-1048578
        self.assertEqual(written, 4096 + 3)

        # Check file size (should be sparse)
        self.assertEqual(os.path.getsize(dst), 1024 * 1024 + 3)

        # Verify destination file is sparse
        dst_stat = os.stat(dst)
        dst_physical = dst_stat.st_blocks * 512
        self.assertLess(dst_physical, dst_stat.st_size)

        # Verify content
        with open(dst, "rb") as f:
            self.assertEqual(f.read(5), b"start")
            f.seek(1024 * 1024)
            self.assertEqual(f.read(3), b"end")

    def test_extract_sparse_with_offset(self):
        """Test extracting sparse region from middle of file."""
        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.bin")

        # Create file: prefix, data at 600, hole, data at 1MB, suffix
        self._create_sparse_file(
            src,
            (0, b"prefix" * 100),
            (600, b"data1"),
            (1024 * 1024, b"data2"),
            (1024 * 1024 + 5, b"suffix" * 100),
        )

        # Extract the sparse region (data1, hole, data2)
        start = 600
        size = 1024 * 1024 - 600 + 5

        written = utils.extract_part_of_file(src, dst, start, size)

        # Should write data regions only (not holes)
        # First region: 600 to first hole (block-aligned ~4096)
        # Second region: 1048576 to 1048580 (5 bytes)
        self.assertEqual(written, (4096 - 600) + 5)

        # Verify destination is sparse
        dst_stat = os.stat(dst)
        self.assertLess(dst_stat.st_blocks * 512, dst_stat.st_size)

        # Verify sparse region extracted correctly
        with open(dst, "rb") as f:
            self.assertEqual(f.read(5), b"data1")
            f.seek(size - 5)
            self.assertEqual(f.read(5), b"data2")

    def test_empty_file_extraction(self):
        """Test extracting from empty file."""
        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.bin")

        with open(src, "wb") as f:
            pass  # Empty file

        written = utils.extract_part_of_file(src, dst, 0, 0)

        self.assertEqual(written, 0)
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"")

    def test_extract_zero_bytes(self):
        """Test requesting zero bytes."""
        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.bin")

        with open(src, "wb") as f:
            f.write(b"hello world")

        written = utils.extract_part_of_file(src, dst, 5, 0)

        self.assertEqual(written, 0)
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"")

    def test_overwrite_existing_file(self):
        """Test that existing destination file is overwritten."""
        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.bin")

        with open(src, "wb") as f:
            f.write(b"new data")

        with open(dst, "wb") as f:
            f.write(b"old data that should be replaced")

        written = utils.extract_part_of_file(src, dst, 0, 8)

        self.assertEqual(written, 8)
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"new data")

    def test_large_file_extraction(self):
        """Test extracting large file to verify chunking works."""
        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.bin")

        # Create 10MB file
        size = 10 * 1024 * 1024
        chunk = b"A" * (1024 * 1024)

        with open(src, "wb") as f:
            for _ in range(10):
                f.write(chunk)

        written = utils.extract_part_of_file(src, dst, 0, size)

        self.assertEqual(written, size)
        self.assertEqual(os.path.getsize(dst), size)

    def test_extract_middle_of_large_file(self):
        """Test extracting from middle of large file."""
        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.bin")

        # Create file with identifiable sections
        with open(src, "wb") as f:
            f.write(b"A" * 1000 + b"B" * 1000 + b"C" * 1000)

        # Extract middle section (the B's)
        written = utils.extract_part_of_file(src, dst, 1000, 1000)

        self.assertEqual(written, 1000)
        with open(dst, "rb") as f:
            self.assertEqual(f.read(), b"B" * 1000)

    def test_convert_to_simg_sparse_file(self):
        """Test converting sparse file to Android sparse image format."""
        import struct

        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.simg")

        # Create sparse file: data, hole, data
        self._create_sparse_file(src, (0, b"A" * 8192), (1024 * 1024, b"B" * 4096))

        utils.convert_to_simg(src, dst)

        # Verify sparse image format
        with open(dst, "rb") as f:
            # Read header
            header = f.read(28)
            (
                magic,
                major,
                minor,
                file_hdr_sz,
                chunk_hdr_sz,
                blk_sz,
                total_blks,
                total_chunks,
                checksum,
            ) = struct.unpack("<IHHHHIIII", header)

            self.assertEqual(magic, 0xED26FF3A)
            self.assertEqual(major, 1)
            self.assertEqual(minor, 0)
            self.assertEqual(file_hdr_sz, 28)
            self.assertEqual(chunk_hdr_sz, 12)
            self.assertEqual(blk_sz, 4096)
            self.assertEqual(total_chunks, 3)  # data, hole, data

            # Read first chunk (data)
            chunk_hdr = struct.unpack("<HHII", f.read(12))
            self.assertEqual(chunk_hdr[0], 0xCAC1)  # RAW
            self.assertEqual(chunk_hdr[2], 2)  # 2 blocks (8192 bytes)
            data = f.read(8192)
            self.assertEqual(data, b"A" * 8192)

            # Read second chunk (hole)
            chunk_hdr = struct.unpack("<HHII", f.read(12))
            self.assertEqual(chunk_hdr[0], 0xCAC3)  # DONT_CARE
            self.assertEqual(chunk_hdr[3], 12)  # header only, no data

            # Read third chunk (data)
            chunk_hdr = struct.unpack("<HHII", f.read(12))
            self.assertEqual(chunk_hdr[0], 0xCAC1)  # RAW
            self.assertEqual(chunk_hdr[2], 1)  # 1 block (4096 bytes)
            data = f.read(4096)
            self.assertEqual(data, b"B" * 4096)

    def test_convert_to_simg_no_holes(self):
        """Test converting non-sparse file to simg."""
        import struct

        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.simg")

        with open(src, "wb") as f:
            f.write(b"X" * 8192)

        utils.convert_to_simg(src, dst)

        with open(dst, "rb") as f:
            header = struct.unpack("<IHHHHIIII", f.read(28))
            self.assertEqual(header[7], 1)  # total_chunks = 1 (just data)

            chunk_hdr = struct.unpack("<HHII", f.read(12))
            self.assertEqual(chunk_hdr[0], 0xCAC1)  # RAW
            self.assertEqual(chunk_hdr[2], 2)  # 2 blocks

    def test_convert_to_simg_all_sparse(self):
        """Test converting entirely sparse file to simg."""
        import struct

        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.simg")

        # Create entirely sparse file using ftruncate
        with open(src, "wb") as f:
            os.ftruncate(f.fileno(), 16384)

        utils.convert_to_simg(src, dst)

        with open(dst, "rb") as f:
            header = struct.unpack("<IHHHHIIII", f.read(28))
            self.assertEqual(header[7], 1)  # total_chunks = 1 (just hole)

            chunk_hdr = struct.unpack("<HHII", f.read(12))
            self.assertEqual(chunk_hdr[0], 0xCAC3)  # DONT_CARE
            self.assertEqual(chunk_hdr[2], 4)  # 4 blocks

    def test_convert_to_simg_unaligned_holes(self):
        """Test conversion with holes that aren't block-aligned.

        This tests the critical case where naive rounding would fail:
        - Data from 0-100 bytes
        - Hole from 100-5000 bytes
        - Data from 5000-5100 bytes

        With 4096-byte blocks, both block 0 and block 1 contain data,
        so there should be NO hole chunks - just 2 consecutive data blocks.
        """
        import struct

        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.simg")

        # Create file with non-block-aligned data regions
        self._create_sparse_file(
            src,
            (0, b"A" * 100),  # Data at start of block 0
            (5000, b"B" * 100),  # Data in block 1 (5000 is in range 4096-8191)
        )

        utils.convert_to_simg(src, dst)

        # Verify sparse image structure
        with open(dst, "rb") as f:
            # Read header
            header = struct.unpack("<IHHHHIIII", f.read(28))
            (
                magic,
                major,
                minor,
                file_hdr_sz,
                chunk_hdr_sz,
                blk_sz,
                total_blks,
                total_chunks,
                checksum,
            ) = header

            self.assertEqual(magic, 0xED26FF3A)
            self.assertEqual(blk_sz, 4096)
            self.assertEqual(total_blks, 2)  # 2 blocks (0-4095, 4096-8191)

            # Should be 1 chunk: both blocks contain data
            self.assertEqual(total_chunks, 1)

            # Read the single chunk (should be RAW type)
            chunk_hdr = struct.unpack("<HHII", f.read(12))
            chunk_type, reserved, chunk_sz, total_sz = chunk_hdr

            self.assertEqual(chunk_type, 0xCAC1)  # RAW
            self.assertEqual(chunk_sz, 2)  # 2 blocks
            self.assertEqual(total_sz, 12 + 2 * 4096)  # header + 2 blocks of data

        # Also validate with simg2img if available
        import shutil
        import subprocess

        if shutil.which("simg2img"):
            restored = os.path.join(self.test_dir, "restored.bin")
            result = subprocess.run(
                ["simg2img", dst, restored],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0)

            # Verify the data regions are preserved
            with open(src, "rb") as f1, open(restored, "rb") as f2:
                # Check first data region
                self.assertEqual(f1.read(100), f2.read(100))

                # Check second data region
                f1.seek(5000)
                f2.seek(5000)
                self.assertEqual(f1.read(100), f2.read(100))

    def test_convert_to_simg_zero_filled_blocks(self):
        """Test that zero-filled blocks generate FILL chunks."""
        import struct

        src = os.path.join(self.test_dir, "source.bin")
        dst = os.path.join(self.test_dir, "dest.simg")

        # Create file with:
        # - Non-zero data blocks
        # - Zero-filled data blocks (not holes!)
        # - More non-zero data
        with open(src, "wb") as f:
            f.write(b"A" * 4096)  # Block 0: non-zero data
            f.write(b"\x00" * (4096 * 10))  # Blocks 1-10: zero-filled data
            f.write(b"B" * 4096)  # Block 11: non-zero data

        utils.convert_to_simg(src, dst)

        # Verify the sparse image structure
        with open(dst, "rb") as f:
            # Read header
            header = struct.unpack("<IHHHHIIII", f.read(28))
            (
                magic,
                major,
                minor,
                file_hdr_sz,
                chunk_hdr_sz,
                blk_sz,
                total_blks,
                total_chunks,
                checksum,
            ) = header

            self.assertEqual(magic, 0xED26FF3A)
            self.assertEqual(total_blks, 12)

            # Should have 3 chunks: RAW, FILL, RAW
            self.assertEqual(total_chunks, 3)

            # First chunk: RAW (1 block of 'A')
            chunk_hdr = struct.unpack("<HHII", f.read(12))
            self.assertEqual(chunk_hdr[0], 0xCAC1)  # RAW
            self.assertEqual(chunk_hdr[2], 1)  # 1 block
            data = f.read(4096)
            self.assertEqual(data, b"A" * 4096)

            # Second chunk: FILL (10 blocks of zeros)
            chunk_hdr = struct.unpack("<HHII", f.read(12))
            self.assertEqual(chunk_hdr[0], 0xCAC2)  # FILL
            self.assertEqual(chunk_hdr[2], 10)  # 10 blocks
            self.assertEqual(chunk_hdr[3], 16)  # total_sz = 12 + 4
            fill_value = struct.unpack("<I", f.read(4))[0]
            self.assertEqual(fill_value, 0)

            # Third chunk: RAW (1 block of 'B')
            chunk_hdr = struct.unpack("<HHII", f.read(12))
            self.assertEqual(chunk_hdr[0], 0xCAC1)  # RAW
            self.assertEqual(chunk_hdr[2], 1)  # 1 block
            data = f.read(4096)
            self.assertEqual(data, b"B" * 4096)

    def test_convert_to_simg_validate_with_simg2img(self):
        """Test conversion validation using android-tools simg2img."""
        import shutil
        import subprocess

        # Check if simg2img is available
        if not shutil.which("simg2img"):
            self.skipTest("simg2img not available")

        src = os.path.join(self.test_dir, "source.bin")
        simg = os.path.join(self.test_dir, "image.simg")
        restored = os.path.join(self.test_dir, "restored.bin")

        # Create test image with sparse regions
        self._create_sparse_file(
            src,
            (0, b"START" * 100),  # 500 bytes
            (8192, b"MIDDLE" * 100),  # 600 bytes at 8KB
            (1024 * 1024, b"END" * 100),  # 300 bytes at 1MB
        )

        # Convert to simg
        utils.convert_to_simg(src, simg)

        # Convert back using simg2img
        result = subprocess.run(
            ["simg2img", simg, restored],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, f"simg2img failed: {result.stderr}")

        # Android sparse format only stores block count, not exact byte size
        # So restored file may be block-aligned (larger than original)
        src_size = os.path.getsize(src)
        restored_size = os.path.getsize(restored)

        # Restored should be at least as large as source
        self.assertGreaterEqual(restored_size, src_size)

        # Restored should be block-aligned
        self.assertEqual(restored_size % 4096, 0)

        # Verify content up to original size matches
        with open(src, "rb") as f1, open(restored, "rb") as f2:
            src_data = f1.read()
            restored_data = f2.read(src_size)
            self.assertEqual(src_data, restored_data)

    def test_convert_to_simg_validate_nonsparse(self):
        """Test conversion of non-sparse file with simg2img validation."""
        import shutil
        import subprocess

        if not shutil.which("simg2img"):
            self.skipTest("simg2img not available")

        src = os.path.join(self.test_dir, "source.bin")
        simg = os.path.join(self.test_dir, "image.simg")
        restored = os.path.join(self.test_dir, "restored.bin")

        # Create non-sparse file with pattern
        with open(src, "wb") as f:
            for i in range(256):
                f.write(bytes([i]) * 256)

        utils.convert_to_simg(src, simg)

        # Convert back
        result = subprocess.run(
            ["simg2img", simg, restored],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, f"simg2img failed: {result.stderr}")

        # Verify exact match
        with open(src, "rb") as f1, open(restored, "rb") as f2:
            self.assertEqual(f1.read(), f2.read())

    def test_convert_to_simg_validate_large_sparse(self):
        """Test conversion of large sparse file with simg2img validation."""
        import shutil
        import subprocess

        if not shutil.which("simg2img"):
            self.skipTest("simg2img not available")

        src = os.path.join(self.test_dir, "source.bin")
        simg = os.path.join(self.test_dir, "image.simg")
        restored = os.path.join(self.test_dir, "restored.bin")

        # Create large sparse file: 100MB logical size with small data regions
        self._create_sparse_file(
            src,
            (0, b"A" * 4096),
            (10 * 1024 * 1024, b"B" * 8192),
            (50 * 1024 * 1024, b"C" * 4096),
            (100 * 1024 * 1024 - 4096, b"D" * 4096),
        )

        utils.convert_to_simg(src, simg)

        # Verify simg file is much smaller than source
        simg_size = os.path.getsize(simg)
        src_size = os.path.getsize(src)
        self.assertLess(simg_size, src_size / 10)

        # Convert back
        result = subprocess.run(
            ["simg2img", simg, restored],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, f"simg2img failed: {result.stderr}")

        # Verify size
        self.assertEqual(os.path.getsize(restored), src_size)

        # Verify data regions match
        with open(src, "rb") as f1, open(restored, "rb") as f2:
            # Check first region
            self.assertEqual(f1.read(4096), f2.read(4096))

            # Check second region
            f1.seek(10 * 1024 * 1024)
            f2.seek(10 * 1024 * 1024)
            self.assertEqual(f1.read(8192), f2.read(8192))

            # Check third region
            f1.seek(50 * 1024 * 1024)
            f2.seek(50 * 1024 * 1024)
            self.assertEqual(f1.read(4096), f2.read(4096))

            # Check last region
            f1.seek(100 * 1024 * 1024 - 4096)
            f2.seek(100 * 1024 * 1024 - 4096)
            self.assertEqual(f1.read(4096), f2.read(4096))
