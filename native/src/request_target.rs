//! Request-target preparation shared by the native HTTP transports.

const HEX: &[u8; 16] = b"0123456789ABCDEF";

pub(crate) fn prepare_request_targets(paths: &mut [String], query: &str) {
    for path in paths {
        prepare_request_target(path, query);
    }
}

pub(crate) fn prepare_request_target(path: &mut String, query: &str) {
    append_query_string(path, query);

    let escaped_bytes = path
        .as_bytes()
        .iter()
        .filter(|byte| !(b'!'..=b'~').contains(byte))
        .count();
    if escaped_bytes == 0 {
        return;
    }

    let mut quoted = String::with_capacity(path.len() + escaped_bytes * 2);
    for byte in path.bytes() {
        if (b'!'..=b'~').contains(&byte) {
            quoted.push(char::from(byte));
        } else {
            quoted.push('%');
            quoted.push(char::from(HEX[usize::from(byte >> 4)]));
            quoted.push(char::from(HEX[usize::from(byte & 0x0f)]));
        }
    }
    *path = quoted;
}

fn append_query_string(path: &mut String, query: &str) {
    if query.is_empty() || path.contains('?') {
        return;
    }

    path.reserve(query.len() + 1);
    if let Some(fragment_index) = path.find('#') {
        // Insert before the fragment to match Python's append_query_string.
        path.insert(fragment_index, '?');
        path.insert_str(fragment_index + 1, query);
    } else {
        path.push('?');
        path.push_str(query);
    }
}
