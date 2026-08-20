use numpy::{PyArray1, PyArrayMethods, PyReadonlyArray1};
use pyo3::prelude::*;
use std::f32::consts::PI;

/// Mirrored Ring Buffer for AVX2/NEON SIMD Vectorized FIR Dot Products.
struct SimdMirroredBuffer {
    buffer: Vec<f32>,
    idx: usize,
    capacity: usize,
}

impl SimdMirroredBuffer {
    fn new(capacity: usize) -> Self {
        Self {
            buffer: vec![0.0; capacity * 2],
            idx: 0,
            capacity,
        }
    }

    #[inline(always)]
    fn push(&mut self, item: f32) {
        self.buffer[self.idx] = item;
        self.buffer[self.idx + self.capacity] = item;
        self.idx = (self.idx + 1) % self.capacity;
    }

    #[inline(always)]
    fn get_contiguous_history(&self, length: usize) -> &[f32] {
        let end = self.idx + self.capacity;
        let start = end - length;
        &self.buffer[start..end]
    }
}

/// Pre-Filled Static Delay Line for Sample-Accurate Lookahead
struct StaticDelayLine {
    buffer: Vec<f32>,
    idx: usize,
    capacity: usize,
}

impl StaticDelayLine {
    fn new(capacity: usize) -> Self {
        Self {
            buffer: vec![0.0; capacity], // Pre-filled with silence
            idx: 0,
            capacity,
        }
    }

    #[inline(always)]
    fn process(&mut self, item: f32) -> f32 {
        let out = self.buffer[self.idx];
        self.buffer[self.idx] = item;
        self.idx = (self.idx + 1) % self.capacity;
        out
    }
}

#[pyclass]
pub struct NativeDialogueDucker {
    sr: usize,
    duck_gain_linear: f32,
    hysteresis_ratio: f32,
    noise_floor_linear: f32,
    ceiling_linear: f32,
    knee_linear: f32,
    up_factor: usize,
    lookahead_samples: usize,
    frame_size: usize,
    hop_size: usize,
    hop_sec: f32,
    alpha_attack: f32,
    alpha_release: f32,
    hold_hops_max: usize,

    // Peak Envelope Ballistics (99% Attenuation in D=192 samples)
    env_attack: f32,
    env_release: f32,
    peak_env: f32,

    // Stateful Trackers
    samples_to_discard: usize,
    dominant_state: usize,
    hold_counter: usize,
    curr_gain_a: f32,
    curr_gain_b: f32,
    last_sample_gain_a: f32,
    last_sample_gain_b: f32,

    // Total input/output length trackers
    total_in_samples: usize,
    total_out_samples: usize,

    // Pre-Allocated Storage (Zero Runtime Allocations)
    delay_buf_a: StaticDelayLine,
    delay_buf_b: StaticDelayLine,
    residue_buf_a: Vec<f32>,
    residue_buf_b: Vec<f32>,
    residue_len: usize,
    limiter_delay_buf: StaticDelayLine,

    fir_hist_up: SimdMirroredBuffer,
    fir_hist_down: SimdMirroredBuffer,

    fir_b_rev: Vec<f32>,
    fir_b_down_rev: Vec<f32>,

    stream_buf_a: Vec<f32>,
    stream_buf_b: Vec<f32>,
    smooth_gain_a: Vec<f32>,
    smooth_gain_b: Vec<f32>,
    curve_a: Vec<f32>,
    curve_b: Vec<f32>,
    mixed_buf: Vec<f32>,
}

#[pymethods]
impl NativeDialogueDucker {
    #[new]
    #[pyo3(signature = (sr=48000, ducking_db=-4.5, hysteresis_db=3.0, hold_time_ms=400.0, attack_ms=20.0, release_ms=300.0, noise_floor_db=-35.0, target_ceiling_db=-1.0, gibbs_margin_db=0.8))]
    pub fn new(
        sr: usize,
        ducking_db: f32,
        hysteresis_db: f32,
        hold_time_ms: f32,
        attack_ms: f32,
        release_ms: f32,
        noise_floor_db: f32,
        target_ceiling_db: f32,
        gibbs_margin_db: f32,
    ) -> Self {
        let duck_gain_linear = 10.0f32.powf(ducking_db / 20.0);
        let hysteresis_ratio = 10.0f32.powf(hysteresis_db / 20.0);
        let noise_floor_linear = 10.0f32.powf(noise_floor_db / 20.0);

        let limit_ceiling_db = target_ceiling_db - gibbs_margin_db;
        let ceiling_linear = 10.0f32.powf(limit_ceiling_db / 20.0);
        let knee_linear = 10.0f32.powf((limit_ceiling_db - 1.5) / 20.0);

        let up_factor = 4;
        let num_taps = 49;
        let group_delay_samples = ((num_taps - 1) / 2) * 2 / up_factor;

        let frame_size = (0.02 * sr as f32) as usize;
        let hop_size = (0.01 * sr as f32) as usize;
        let hop_sec = hop_size as f32 / sr as f32;

        let alpha_attack = (-hop_sec / (attack_ms / 1000.0)).exp();
        let alpha_release = (-hop_sec / (release_ms / 1000.0)).exp();
        let hold_hops_max = ((hold_time_ms / 1000.0) / hop_sec) as usize;

        // 1ms True Lookahead Delay Buffer Size @ 192kHz (D = 192 samples)
        let limiter_delay_len = (0.001 * (sr * up_factor) as f32) as usize;

        // Corrected 99.0% Target Time Constant Calculation: ln(0.01) / D
        let env_attack = ((0.01f32).ln() / (limiter_delay_len as f32)).exp();
        let env_release = ((0.01f32).ln() / (0.010 * (sr * up_factor) as f32)).exp();

        let lookahead_samples = ((attack_ms / 1000.0) * sr as f32) as usize;

        let mut fir_b = vec![0.0f32; num_taps];
        let m = (num_taps - 1) as f32 / 2.0;
        let fc = 1.0 / up_factor as f32;

        for n in 0..num_taps {
            let nf = n as f32;
            let window = 0.54 - 0.46 * ((2.0 * PI * nf) / (num_taps - 1) as f32).cos();
            let h = if (nf - m).abs() < 1e-5 {
                fc
            } else {
                (PI * fc * (nf - m)).sin() / (PI * (nf - m))
            };
            fir_b[n] = h * window * (up_factor as f32);
        }

        let mut fir_b_rev = fir_b.clone();
        fir_b_rev.reverse();
        let fir_b_down_rev: Vec<f32> = fir_b_rev.iter().map(|&v| v / up_factor as f32).collect();

        let max_block_size = sr * 2;

        Self {
            sr,
            duck_gain_linear,
            hysteresis_ratio,
            noise_floor_linear,
            ceiling_linear,
            knee_linear,
            up_factor,
            lookahead_samples,
            frame_size,
            hop_size,
            hop_sec,
            alpha_attack,
            alpha_release,
            hold_hops_max,
            env_attack,
            env_release,
            peak_env: 1.0,
            samples_to_discard: group_delay_samples,
            dominant_state: 0,
            hold_counter: 0,
            curr_gain_a: 1.0,
            curr_gain_b: 1.0,
            last_sample_gain_a: 1.0,
            last_sample_gain_b: 1.0,
            total_in_samples: 0,
            total_out_samples: 0,
            delay_buf_a: StaticDelayLine::new(lookahead_samples),
            delay_buf_b: StaticDelayLine::new(lookahead_samples),
            residue_buf_a: vec![0.0; max_block_size],
            residue_buf_b: vec![0.0; max_block_size],
            residue_len: 0,
            limiter_delay_buf: StaticDelayLine::new(limiter_delay_len),
            fir_hist_up: SimdMirroredBuffer::new(num_taps),
            fir_hist_down: SimdMirroredBuffer::new(num_taps),
            fir_b_rev,
            fir_b_down_rev,
            stream_buf_a: vec![0.0; max_block_size],
            stream_buf_b: vec![0.0; max_block_size],
            smooth_gain_a: vec![0.0; max_block_size / hop_size],
            smooth_gain_b: vec![0.0; max_block_size / hop_size],
            curve_a: vec![0.0; max_block_size],
            curve_b: vec![0.0; max_block_size],
            mixed_buf: vec![0.0; max_block_size],
        }
    }

    /// ZERO-COPY IN-PLACE FFI MUTATION
    pub fn process_chunk_inplace<'py>(
        &mut self,
        py: Python<'py>,
        raw_a: PyReadonlyArray1<'py, f32>,
        raw_b: PyReadonlyArray1<'py, f32>,
        raw_out: Bound<'py, PyArray1<f32>>,
    ) -> PyResult<usize> {
        let slice_a = raw_a.as_slice()?;
        let slice_b = raw_b.as_slice()?;
        let slice_out = unsafe { raw_out.as_slice_mut()? };

        let num_samples = py.allow_threads(|| {
            self.process_internal(slice_a, slice_b, slice_out)
        });

        Ok(num_samples)
    }

    pub fn flush_inplace<'py>(
        &mut self,
        py: Python<'py>,
        raw_out: Bound<'py, PyArray1<f32>>,
    ) -> PyResult<usize> {
        let slice_out = unsafe { raw_out.as_slice_mut()? };

        let num_samples = py.allow_threads(|| {
            let drain_size = self.lookahead_samples + self.frame_size + self.residue_len + 12;
            let zeros_a = vec![0.0f32; drain_size];
            let zeros_b = vec![0.0f32; drain_size];
            let target_in = self.total_in_samples;
            let out_len = self.process_internal(&zeros_a, &zeros_b, slice_out);
            
            let needed = if target_in > (self.total_out_samples - out_len) {
                target_in - (self.total_out_samples - out_len)
            } else {
                0
            };
            out_len.min(needed)
        });

        Ok(num_samples)
    }
}

impl NativeDialogueDucker {
    fn process_internal(&mut self, raw_a: &[f32], raw_b: &[f32], out: &mut [f32]) -> usize {
        let mut stream_len = 0;
        self.total_in_samples += raw_a.len();

        if self.residue_len > 0 {
            self.stream_buf_a[..self.residue_len].copy_from_slice(&self.residue_buf_a[..self.residue_len]);
            self.stream_buf_b[..self.residue_len].copy_from_slice(&self.residue_buf_b[..self.residue_len]);
            stream_len = self.residue_len;
        }

        let copy_a = raw_a.len().min(self.stream_buf_a.len() - stream_len);
        self.stream_buf_a[stream_len..stream_len + copy_a].copy_from_slice(&raw_a[..copy_a]);
        let copy_b = raw_b.len().min(self.stream_buf_b.len() - stream_len);
        self.stream_buf_b[stream_len..stream_len + copy_b].copy_from_slice(&raw_b[..copy_b]);
        stream_len += copy_a.min(copy_b);

        if stream_len < self.frame_size {
            self.residue_buf_a[..stream_len].copy_from_slice(&self.stream_buf_a[..stream_len]);
            self.residue_buf_b[..stream_len].copy_from_slice(&self.stream_buf_b[..stream_len]);
            self.residue_len = stream_len;
            return 0;
        }

        let num_hops = (stream_len - self.frame_size) / self.hop_size;
        let processed_samples = num_hops * self.hop_size;

        for h in 0..num_hops {
            let idx = h * self.hop_size;
            let sum_sq_a: f32 = self.stream_buf_a[idx..idx + self.frame_size].iter().map(|&v| v * v).sum();
            let sum_sq_b: f32 = self.stream_buf_b[idx..idx + self.frame_size].iter().map(|&v| v * v).sum();

            let rms_a = (sum_sq_a / self.frame_size as f32).sqrt() + 1e-9;
            let rms_b = (sum_sq_b / self.frame_size as f32).sqrt() + 1e-9;

            if rms_a > self.noise_floor_linear && rms_b > self.noise_floor_linear {
                if self.hold_counter > 0 {
                    self.hold_counter -= 1;
                } else if self.dominant_state == 0 {
                    if rms_a >= rms_b * self.hysteresis_ratio {
                        self.dominant_state = 1; self.hold_counter = self.hold_hops_max;
                    } else if rms_b >= rms_a * self.hysteresis_ratio {
                        self.dominant_state = 2; self.hold_counter = self.hold_hops_max;
                    }
                } else if self.dominant_state == 1 && rms_b >= rms_a * self.hysteresis_ratio {
                    self.dominant_state = 2; self.hold_counter = self.hold_hops_max;
                } else if self.dominant_state == 2 && rms_a >= rms_b * self.hysteresis_ratio {
                    self.dominant_state = 1; self.hold_counter = self.hold_hops_max;
                }
            } else if self.hold_counter > 0 {
                self.hold_counter -= 1;
            } else {
                self.dominant_state = 0;
            }

            let (tgt_a, tgt_b) = match self.dominant_state {
                1 => (1.0, self.duck_gain_linear),
                2 => (self.duck_gain_linear, 1.0),
                _ => (1.0, 1.0),
            };

            self.curr_gain_a = if tgt_a < self.curr_gain_a { self.alpha_attack * self.curr_gain_a + (1.0 - self.alpha_attack) * tgt_a } else { self.alpha_release * self.curr_gain_a + (1.0 - self.alpha_release) * tgt_a };
            self.smooth_gain_a[h] = self.curr_gain_a;

            self.curr_gain_b = if tgt_b < self.curr_gain_b { self.alpha_attack * self.curr_gain_b + (1.0 - self.alpha_attack) * tgt_b } else { self.alpha_release * self.curr_gain_b + (1.0 - self.alpha_release) * tgt_b };
            self.smooth_gain_b[h] = self.curr_gain_b;
        }

        for i in 0..processed_samples {
            let hop_idx = i / self.hop_size;
            let frac = (i % self.hop_size) as f32 / self.hop_size as f32;

            let prev_a = if hop_idx == 0 { self.last_sample_gain_a } else { self.smooth_gain_a[hop_idx - 1] };
            let prev_b = if hop_idx == 0 { self.last_sample_gain_b } else { self.smooth_gain_b[hop_idx - 1] };

            self.curve_a[i] = prev_a + frac * (self.smooth_gain_a[hop_idx] - prev_a);
            self.curve_b[i] = prev_b + frac * (self.smooth_gain_b[hop_idx] - prev_b);
        }

        self.last_sample_gain_a = self.curve_a[processed_samples - 1];
        self.last_sample_gain_b = self.curve_b[processed_samples - 1];

        for i in 0..processed_samples {
            let delayed_sample_a = self.delay_buf_a.process(self.stream_buf_a[i]);
            let delayed_sample_b = self.delay_buf_b.process(self.stream_buf_b[i]);
            self.mixed_buf[i] = delayed_sample_a * self.curve_a[i] + delayed_sample_b * self.curve_b[i];
        }

        self.residue_len = stream_len - processed_samples;
        if self.residue_len > 0 {
            self.residue_buf_a[..self.residue_len].copy_from_slice(&self.stream_buf_a[processed_samples..stream_len]);
            self.residue_buf_b[..self.residue_len].copy_from_slice(&self.stream_buf_b[processed_samples..stream_len]);
        }

        let out_len = self.true_peak_limit_simd(processed_samples, out);
        self.total_out_samples += out_len;
        out_len
    }

    fn true_peak_limit_simd(&mut self, input_len: usize, out_arr: &mut [f32]) -> usize {
        let delta = self.ceiling_linear - self.knee_linear;
        let mut out_idx = 0;
        let taps = self.fir_b_rev.len();

        for i in 0..input_len {
            let sample = self.mixed_buf[i];

            for u in 0..self.up_factor {
                let up_sample = if u == 0 { sample } else { 0.0 };
                self.fir_hist_up.push(up_sample);

                let hist_slice = self.fir_hist_up.get_contiguous_history(taps);
                let up_filtered: f32 = hist_slice.iter()
                    .zip(self.fir_b_rev.iter())
                    .map(|(x, h)| x * h)
                    .sum();

                // 1. CALCULATE TARGET GAIN ON UN-DELAYED PEAK
                let abs_s = up_filtered.abs();
                let target_env = if abs_s > self.knee_linear {
                    self.knee_linear / abs_s
                } else {
                    1.0
                };

                // Ballistic Envelope Ramping over D=192 samples (99.0% Attenuation)
                if target_env < self.peak_env {
                    self.peak_env = self.env_attack * self.peak_env + (1.0 - self.env_attack) * target_env;
                } else {
                    self.peak_env = self.env_release * self.peak_env + (1.0 - self.env_release) * target_env;
                }

                // 2. EXTRACT DELAYED AUDIO SAMPLE (Delayed by D=192 samples)
                let delayed_audio = self.limiter_delay_buf.process(up_filtered);

                // 3. APPLY PEAK-ALIGNED ENVELOPE (99% Attenuation reached exactly as peak exits)
                let mut env_scaled = delayed_audio * self.peak_env;

                let final_abs = env_scaled.abs();
                if final_abs > self.knee_linear {
                    env_scaled = env_scaled.signum() * (self.knee_linear + delta * ((final_abs - self.knee_linear) / delta).tanh());
                }

                self.fir_hist_down.push(env_scaled);

                if u == 0 {
                    let down_hist = self.fir_hist_down.get_contiguous_history(taps);
                    let down_filtered: f32 = down_hist.iter()
                        .zip(self.fir_b_down_rev.iter())
                        .map(|(x, h)| x * h)
                        .sum();

                    if self.samples_to_discard > 0 {
                        self.samples_to_discard -= 1;
                    } else if out_idx < out_arr.len() {
                        out_arr[out_idx] = down_filtered;
                        out_idx += 1;
                    }
                }
            }
        }

        out_idx
    }
}
