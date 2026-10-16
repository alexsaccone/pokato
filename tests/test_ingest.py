import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image
from pokato.vision.layouts import Layout, Region, Example
from pokato.vision.sources import ImageSource, VideoSource, CaptureSource, rgb_image


class IngestTests(unittest.TestCase):
    def test_different_image_formats_and_aspects_preserve_pixels_and_order(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder)/name for name in ("wide.png", "tall.bmp", "square.webp")]
            for path, size, color in zip(paths, ((400, 120), (120, 400), (250, 250)), ("red", "blue", "green")):
                Image.new("RGB", size, color).save(path, lossless=True)
            source = ImageSource(paths)
            frames = [source.next() for _ in paths]
            self.assertEqual([f.image.size for f in frames], [(400, 120), (120, 400), (250, 250)])
            self.assertEqual([f.index for f in frames], [0, 1, 2])
            self.assertEqual(frames[1].image.getpixel((10, 10)), (0, 0, 255))
            self.assertIsNone(source.next())
            source.close()
            self.assertIsNone(source.next())

    def test_animated_image_frames_and_alpha(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"frames.gif"
            Image.new("RGB", (90, 60), "red").save(path, save_all=True, append_images=[Image.new("RGB", (90, 60), "blue")], duration=100)
            source = ImageSource([path])
            self.assertEqual(source.next().image.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(source.next().image.getpixel((0, 0)), (0, 0, 255))
            self.assertIsNone(source.next())
            source.close()
        self.assertEqual(rgb_image(Image.new("RGBA", (20, 20), (0, 0, 0, 0))).getpixel((0, 0)), (255, 255, 255))

    def test_local_video_decoding_order_eof_and_close(self):
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"fixture.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5, (160, 120))
            self.assertTrue(writer.isOpened())
            for value in (20, 80, 140):
                writer.write(np.full((120, 160, 3), value, dtype=np.uint8))
            writer.release()
            source = VideoSource(path)
            frames = [source.next() for _ in range(3)]
            self.assertEqual([f.timestamp for f in frames], [0., .2, .4])
            self.assertAlmostEqual(frames[-1].image.getpixel((10, 10))[0], 140, delta=3)
            self.assertIsNone(source.next())
            source.close()
            self.assertIsNone(source.next())

    def test_portable_calibration_roundtrip_and_relative_regions(self):
        region = Region("hole0.rank", (.1, .2, .2, .4), "rank")
        self.assertEqual(region.pixels((1000, 500)), (100, 100, 200, 200))
        self.assertEqual(region.pixels((2000, 1000)), (200, 200, 400, 400))
        layout = Layout(name="Any skin", reference_size=(1200, 700), chip_unit="0.01", regions={region.name: region})
        layout.examples.append(Example.create(region, "A", Image.new("RGB", (20, 30), "black")))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"layout.json"
            layout.save(path)
            loaded = Layout.load(path)
            self.assertEqual(loaded, layout)
            self.assertEqual(loaded.examples[0].image().size, (20, 30))

    def test_bad_profiles_bounds_and_sources_are_rejected(self):
        for box in ((0, 0, 0, 1), (-1, 0, 1, 1), (0, 0, 2, 1), (0, 0, float("nan"), 1)):
            with self.subTest(box=box), self.assertRaises(ValueError):
                Region("pot", box, "number")
        with self.assertRaises(ValueError):
            CaptureSource(bounds=(20, 20, 0, 0))
        with self.assertRaises(ValueError):
            CaptureSource()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"bad.json"
            for data in ([], {"version": 99}, {"version": 1, "reference_size": [1, 1]}):
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ValueError):
                    Layout.load(path)


if __name__ == "__main__":
    unittest.main()
