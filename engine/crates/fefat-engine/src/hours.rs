//! When the market is open, for F-SES-02, as `fefat.reference.hours` reads it: records received in
//! the break after a session's close or inside a halt are not tradeable. An instrument without a
//! calendar, such as a scenario's inline instrument, trades around the clock.

use fefat_core::instants::Ts;

/// A halt inside a session, from `start` to just before `end`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Halt {
    /// The instant trading stops.
    pub start: Ts,
    /// The instant trading resumes.
    pub end: Ts,
}

/// A session of the instrument's calendar, open from `open` to just before `close`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Session {
    /// The instant it opens.
    pub open: Ts,
    /// The instant it closes.
    pub close: Ts,
    /// Its halts.
    pub halts: Vec<Halt>,
}

/// When the market trades: always, or in the sessions of a calendar, ordered by their opens.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TradingHours {
    sessions: Option<Vec<Session>>,
}

impl TradingHours {
    /// Hours of a product without a calendar, which trades around the clock.
    pub const fn always() -> Self {
        Self { sessions: None }
    }

    /// The hours of `sessions`, given in any order.
    pub fn of_sessions(mut sessions: Vec<Session>) -> Self {
        sessions.sort_by_key(|session| session.open);
        Self {
            sessions: Some(sessions),
        }
    }

    /// Whether the market trades at `instant`: inside the last session opened at or before it,
    /// before its close, and outside its halts (`CalendarHours.is_open`).
    pub fn is_open(&self, instant: Ts) -> bool {
        let Some(sessions) = &self.sessions else {
            return true;
        };
        let opened = sessions.partition_point(|session| session.open <= instant);
        let Some(session) = opened.checked_sub(1).and_then(|last| sessions.get(last)) else {
            return false;
        };
        let halted = session
            .halts
            .iter()
            .any(|halt| halt.start <= instant && instant < halt.end);
        instant < session.close && !halted
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_session_is_open_from_its_open_to_just_before_its_close_outside_its_halts() {
        let session = Session {
            open: Ts(100),
            close: Ts(200),
            halts: vec![Halt {
                start: Ts(150),
                end: Ts(160),
            }],
        };
        let later = Session {
            open: Ts(300),
            close: Ts(400),
            halts: vec![],
        };
        let hours = TradingHours::of_sessions(vec![later, session]);
        let open = [99, 100, 149, 150, 159, 160, 199, 200, 299, 300, 399, 400];
        let expected = [
            false, true, true, false, false, true, true, false, false, true, true, false,
        ];
        let read: Vec<bool> = open.iter().map(|&at| hours.is_open(Ts(at))).collect();
        assert_eq!(read, expected);
        assert!(TradingHours::always().is_open(Ts(i64::MIN)));
    }
}
