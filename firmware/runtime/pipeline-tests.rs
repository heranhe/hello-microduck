#[cfg(test)]
mod hello_calibration_tests {
    use super::*;
    use gst_video::VideoFrameExt;

    // Exercise the exact element builder used before the production tee, with real pixels.
    fn pixels(rotation: Rotation, fine: f64, mirror: bool) -> (u32, u32, Vec<u8>) {
        gst::init().unwrap();
        let pipeline = gst::Pipeline::new();
        let src = gst_app::AppSrc::builder()
            .format(gst::Format::Time)
            .caps(&gst::Caps::builder("video/x-raw")
                .field("format", "UYVY").field("width", 4i32).field("height", 2i32)
                .field("framerate", gst::Fraction::new(1, 1)).build()).build();
        let sink = gst_app::AppSink::builder().sync(false).build();
        pipeline.add_many([src.upcast_ref::<gst::Element>(), sink.upcast_ref::<gst::Element>()]).unwrap();
        let value = crate::calibration::Calibration {
            rotation: 0, fine_degrees: fine, mirror_horizontal: mirror, mirror_vertical: false,
        };
        let mut transforms = Vec::new();
        if let Some(direction) = rotation.video_direction() {
            transforms.push(gst::ElementFactory::make("videoflip")
                .property_from_str("video-direction", direction).build().unwrap());
        }
        transforms.extend(calibration_elements(Some(&value)).unwrap());
        for element in &transforms { pipeline.add(element).unwrap(); }
        let mut chain: Vec<&gst::Element> = vec![src.upcast_ref()];
        chain.extend(transforms.iter()); chain.push(sink.upcast_ref());
        gst::Element::link_many(chain).unwrap();
        pipeline.set_state(gst::State::Playing).unwrap();
        let input = vec![128,10,128,20,128,30,128,40,128,50,128,60,128,70,128,80];
        src.push_buffer(gst::Buffer::from_mut_slice(input)).unwrap();
        src.end_of_stream().unwrap();
        let sample = sink.try_pull_sample(gst::ClockTime::from_seconds(5)).expect("transformed frame");
        let caps = gst_video::VideoInfo::from_caps(sample.caps().unwrap()).unwrap();
        let buffer = sample.buffer().unwrap();
        let mapped = gst_video::VideoFrameRef::from_buffer_ref_readable(buffer, &caps).unwrap();
        let stride = mapped.plane_stride()[0] as usize;
        let data = mapped.plane_data(0).unwrap();
        let mut luma = Vec::new();
        for y in 0..caps.height() as usize {
            for x in 0..caps.width() as usize { luma.push(data[y*stride+x*2+1]); }
        }
        pipeline.set_state(gst::State::Null).unwrap();
        (caps.width(), caps.height(), luma)
    }

    #[test]
    fn quarter_turn_changes_pixels_and_dimensions() {
        assert_eq!(pixels(Rotation::Cw90, 0.0, false), (2, 4, vec![50,10,60,20,70,30,80,40]));
    }
    #[test]
    fn mirror_is_applied_after_direction() {
        assert_eq!(pixels(Rotation::Cw90, 0.0, true), (2, 4, vec![10,50,20,60,30,70,40,80]));
    }
    #[test]
    fn fine_angle_modifies_the_frame_without_changing_its_geometry() {
        let original = pixels(Rotation::None, 0.0, false);
        let tilted = pixels(Rotation::None, 30.0, false);
        assert_eq!((tilted.0, tilted.1), (original.0, original.1));
        assert_ne!(tilted.2, original.2);
    }
}
