//! Floats as the backtest-expert skill's `evaluate_backtest.py` writes them into its red flags'
//! messages: by Python's `repr`, and to three places, as Python's `:.3f` rounds a tie to the even
//! digit, which Rust's formatting does too (step 2.11).

/// A finite float as Python's `repr` writes it: its shortest digits, fixed from 1e-4 up to below
/// 1e16 with at least one place, `61.5` and `60.0`, else in exponent form, `1e-05` and `1.5e+16`;
/// infinity and NaN as Rust writes them, which no drawdown is.
pub(crate) fn python_float_text(value: f64) -> String {
    let scientific = format!("{value:e}");
    let parts = scientific.split_once('e');
    let Some((mantissa, Ok(exponent))) =
        parts.map(|(digits, power)| (digits, power.parse::<i32>()))
    else {
        return scientific;
    };
    if !(-4..16).contains(&exponent) {
        let sign = if exponent < 0 { '-' } else { '+' };
        return format!("{mantissa}e{sign}{:02}", exponent.unsigned_abs());
    }
    let (sign, unsigned) = mantissa
        .strip_prefix('-')
        .map_or(("", mantissa), |digits| ("-", digits));
    let digits: String = unsigned.chars().filter(char::is_ascii_digit).collect();
    if exponent < 0 {
        let zeros = "0".repeat(exponent.unsigned_abs() as usize - 1);
        return format!("{sign}0.{zeros}{digits}");
    }
    let whole = exponent.unsigned_abs() as usize + 1;
    let padded = format!("{digits:0<whole$}");
    let (integer, fraction) = padded.split_at(whole);
    let fraction = if fraction.is_empty() { "0" } else { fraction };
    format!("{sign}{integer}.{fraction}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn floats_read_as_python_writes_them() {
        let texts: Vec<String> = [
            61.5,
            60.0,
            50.000_000_000_000_01,
            1e-5,
            1e-4,
            1.5e16,
            1e15,
            123.456,
        ]
        .into_iter()
        .map(python_float_text)
        .collect();
        assert_eq!(
            texts,
            [
                "61.5",
                "60.0",
                "50.00000000000001",
                "1e-05",
                "0.0001",
                "1.5e+16",
                "1000000000000000.0",
                "123.456"
            ]
        );
        assert_eq!(format!("{:.3}", -0.0625_f64), "-0.062");
        assert_eq!(format!("{:.3}", -0.0005_f64), "-0.001");
        assert_eq!(format!("{:.3}", -0.1875_f64), "-0.188");
        assert_eq!(format!("{:.3}", -1.0005_f64), "-1.000");
    }
}
