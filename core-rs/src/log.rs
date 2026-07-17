//! Tick log entries and a generic before/after diff. Ported from `log.py`.
//! One diff() function handles every action - no per-action special-casing.

use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeSet;
use std::fs::File;
use std::io::{BufWriter, Write};

#[derive(Serialize, Clone)]
pub struct TickLogEntry {
    pub tick: i64,
    pub agent_id: String,
    pub tier: String,
    pub state_before: Value,
    pub action: String,
    pub target: Option<String>,
    pub success: bool,
    pub state_after: Value,
    pub delta: Value,
}

fn round3(v: f64) -> f64 {
    (v * 1000.0).round() / 1000.0
}

/// Flat diff of two agent snapshot objects; only reports changed keys.
/// Inventory is diffed sub-key by sub-key (inventory.<resource>). Booleans are
/// checked before the numeric branch to keep `alive` a literal true/false, not a delta.
pub fn diff(before: &Value, after: &Value) -> Value {
    let mut changes = serde_json::Map::new();
    let after_obj = after.as_object().expect("snapshot must be an object");
    let empty = serde_json::Map::new();
    let before_obj = before.as_object().unwrap_or(&empty);

    for (key, a_val) in after_obj.iter() {
        if key == "inventory" {
            let empty_inv = serde_json::Map::new();
            let inv_before = before_obj.get("inventory").and_then(|v| v.as_object()).unwrap_or(&empty_inv);
            let inv_after = a_val.as_object().unwrap_or(&empty_inv);
            let mut keys: BTreeSet<String> = BTreeSet::new();
            keys.extend(inv_before.keys().cloned());
            keys.extend(inv_after.keys().cloned());
            for res in keys {
                let b = inv_before.get(&res).and_then(|v| v.as_f64()).unwrap_or(0.0);
                let a = inv_after.get(&res).and_then(|v| v.as_f64()).unwrap_or(0.0);
                if (a - b).abs() > 1e-9 {
                    changes.insert(format!("inventory.{res}"), serde_json::json!(round3(a - b)));
                }
            }
            continue;
        }

        let b_val = before_obj.get(key);
        if b_val == Some(a_val) {
            continue;
        }
        if a_val.is_boolean() || b_val.map(|v| v.is_boolean()).unwrap_or(false) {
            changes.insert(key.clone(), a_val.clone());
        } else if let (Some(a_num), Some(b_num)) = (a_val.as_f64(), b_val.and_then(|v| v.as_f64())) {
            changes.insert(key.clone(), serde_json::json!(round3(a_num - b_num)));
        } else {
            changes.insert(key.clone(), a_val.clone());
        }
    }
    Value::Object(changes)
}

pub struct JsonlWriter {
    writer: BufWriter<File>,
}

impl JsonlWriter {
    pub fn new(path: &str) -> Self {
        let file = File::create(path).expect("cannot create log file");
        JsonlWriter { writer: BufWriter::new(file) }
    }

    /// Generic over T rather than tied to TickLogEntry - lets a caller with
    /// extra context (e.g. serve_main.rs's society lookup) write an enriched
    /// value through the same writer, without TickLogEntry itself needing to
    /// know about anything outside the tick engine.
    pub fn write<T: Serialize>(&mut self, entry: &T) {
        let line = serde_json::to_string(entry).expect("log entry must serialize");
        writeln!(self.writer, "{line}").expect("write to log file");
    }

    pub fn close(mut self) {
        self.writer.flush().expect("flush log file");
    }
}
