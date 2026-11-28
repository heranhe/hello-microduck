//! Persistent pixel calibration applied before every camera consumer.
use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::path::Path;

pub const PATH: &str = "/etc/robot/camera-calibration.json";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Calibration {
    pub rotation: u32,
    pub fine_degrees: f64,
    pub mirror_horizontal: bool,
    pub mirror_vertical: bool,
}

impl Calibration {
    pub fn load(path: &Path) -> Result<Option<Self>> {
        let data = match std::fs::read(path) {
            Ok(data) => data,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(e).context("reading camera calibration"),
        };
        let value: Self = serde_json::from_slice(&data).context("invalid camera calibration")?;
        value.validate()?;
        Ok(Some(value))
    }

    pub fn validate(&self) -> Result<()> {
        if ![0, 90, 180, 270].contains(&self.rotation) {
            bail!("rotation must be 0, 90, 180 or 270");
        }
        if !self.fine_degrees.is_finite() || self.fine_degrees.abs() > 45.0 {
            bail!("fine_degrees must be finite and within -45..45");
        }
        Ok(())
    }

    pub fn output(&self, width: u32, height: u32) -> (u32, u32) {
        if self.rotation == 90 || self.rotation == 270 { (height, width) } else { (width, height) }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_corrupt_calibration_instead_of_silently_changing_pixels() {
        for text in [r#"{"rotation":45,"fine_degrees":0,"mirror_horizontal":false,"mirror_vertical":false}"#,
                     r#"{"rotation":90,"fine_degrees":46,"mirror_horizontal":false,"mirror_vertical":false}"#] {
            let value: Calibration = serde_json::from_str(text).unwrap();
            assert!(value.validate().is_err());
        }
    }
    #[test]
    fn restart_reads_saved_geometry() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("camera.json");
        assert!(Calibration::load(&path).unwrap().is_none());
        std::fs::write(&path, r#"{"rotation":270,"fine_degrees":-2.5,"mirror_horizontal":true,"mirror_vertical":false}"#).unwrap();
        let value = Calibration::load(&path).unwrap().unwrap();
        assert_eq!(value.output(640, 360), (360, 640));
        assert_eq!(Calibration::load(&path).unwrap(), Some(value));
    }
}
