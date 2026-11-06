#!/usr/bin/env python3
"""Apply the Hello camera patch only to the pinned community source tree."""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
here = Path(__file__).resolve().parent

def edit(relative, old, new, count=1):
    path = root / relative
    text = path.read_text()
    if text.count(old) != count:
        raise SystemExit(f'Unexpected upstream source: {relative}: {old[:80]!r}')
    path.write_text(text.replace(old, new))

shutil.copyfile(here/'runtime/calibration.rs', root/'mediad/src/calibration.rs')
edit('mediad/src/lib.rs', 'pub mod camera;', 'pub mod camera;\npub mod calibration;')
edit('mediad/src/main.rs', '    flip_in_pipeline: bool,', '''    flip_in_pipeline: bool,

    /// Persisted pixel calibration, applied to every downstream consumer.
    #[arg(long, default_value = mediad::calibration::PATH)]
    calibration: PathBuf,

    /// Validate saved calibration and required plugins without opening the camera.
    #[arg(long)]
    check_calibration: bool,''')
edit('mediad/src/main.rs', '    let args = Args::parse();', '''    let mut args = Args::parse();
    let calibration = match mediad::calibration::Calibration::load(
        &args.calibration) {
        Ok(value) => value,
        Err(error) => { eprintln!("camera calibration: {error:#}"); return ExitCode::FAILURE; }
    };
    if args.check_calibration {
        return match mediad::pipeline::check_calibration(calibration.as_ref()) {
            Ok(()) => ExitCode::SUCCESS,
            Err(error) => { eprintln!("camera plugins: {error:#}"); ExitCode::FAILURE }
        };
    }
    if let Some(value) = &calibration {
        args.rotate = Some(value.rotation);
        args.flip_in_pipeline = true;
    }''')
edit('mediad/src/main.rs', '            rotation,\n        };', '            rotation,\n            calibration: calibration.clone(),\n        };')
edit('mediad/src/main.rs', '        let intrinsics = if args.sim_camera.is_some() {', '        let intrinsics = if calibration.is_some() || args.flip_in_pipeline {\n            // Sensor-space intrinsics are invalid after a pixel transform.\n            None\n        } else if args.sim_camera.is_some() {')
edit('mediad/src/main.rs', '''        let video = mediad::session::Video {
            width,
            height,
            rotate,
            intrinsics,
        };''', '''        let (video_width, video_height) = calibration.as_ref()
            .map(|c| c.output(width, height))
            .unwrap_or(if args.flip_in_pipeline && [90, 270].contains(&rotate) {
                (height, width)
            } else { (width, height) });
        let video = mediad::session::Video {
            width: video_width,
            height: video_height,
            rotate: frame_rotate,
            intrinsics,
        };''')
edit('mediad/src/main.rs', '            rotate,\n            &args.token,', '            frame_rotate,\n            &args.token,')
edit('mediad/src/pipeline.rs', '#[derive(Debug, Clone, PartialEq, Eq)]\npub struct Settings', '#[derive(Debug, Clone, PartialEq)]\npub struct Settings')
edit('mediad/src/pipeline.rs', '    pub rotation: Rotation,', '    pub rotation: Rotation,\n    pub calibration: Option<crate::calibration::Calibration>,')
edit('mediad/src/pipeline.rs', '            rotation: Rotation::None,', '            rotation: Rotation::None,\n            calibration: None,')
edit('mediad/src/pipeline.rs', '    let tee = make("tee")?;', '''    let correction = calibration_elements(settings.calibration.as_ref())?;
    for element in &correction { pipeline.add(element)?; }
    let tee = make("tee")?;''')
edit('mediad/src/pipeline.rs', '''    match flip.as_ref() {
        Some(flip) => gst::Element::link_many([&capsfilter, flip, &tee]),
        None => gst::Element::link_many([&capsfilter, &tee]),
    }''', '''    let mut calibrated = vec![&capsfilter];
    if let Some(flip) = &flip { calibrated.push(flip); }
    calibrated.extend(correction.iter());
    calibrated.push(&tee);
    gst::Element::link_many(calibrated)''')
# All transformations precede the raw/WebRTC/H264 tee. Never use a display-only fix.
with (root/'mediad/src/pipeline.rs').open('a') as out:
    out.write('''
pub fn check_calibration(calibration: Option<&crate::calibration::Calibration>) -> Result<()> {
    gst::init()?;
    if let Some(c) = calibration {
        c.validate()?;
        if let Some(direction) = Rotation::from_degrees(c.rotation)?.video_direction() {
            gst::ElementFactory::make("videoflip")
                .property_from_str("video-direction", direction).build()?;
        }
    }
    calibration_elements(calibration)?;
    Ok(())
}

fn calibration_elements(calibration: Option<&crate::calibration::Calibration>) -> Result<Vec<gst::Element>> {
    let mut elements = Vec::new();
    if let Some(c) = calibration {
        c.validate()?;
        let direction = match (c.mirror_horizontal, c.mirror_vertical) {
            (true, true) => Some("180"),
            (true, false) => Some("horiz"),
            (false, true) => Some("vert"),
            _ => None,
        };
        if let Some(direction) = direction {
            elements.push(gst::ElementFactory::make("videoflip")
                .property_from_str("video-direction", direction).build()?);
        }
        if c.fine_degrees != 0.0 {
            elements.push(gst::ElementFactory::make("videoconvert").build()?);
            elements.push(gst::ElementFactory::make("rotate")
                .property("angle", c.fine_degrees.to_radians())
                .property_from_str("off-edge-pixels", "black").build()?);
            elements.push(gst::ElementFactory::make("videoconvert").build()?);
            elements.push(gst::ElementFactory::make("capsfilter")
                .property("caps", gst::Caps::builder("video/x-raw")
                    .field("format", CAPTURE_FORMAT).build()).build()?);
        }
    }
    Ok(elements)
}
''')
    out.write((here/'runtime/pipeline-tests.rs').read_text())
print('Hello firmware pixel-calibration patch applied')
