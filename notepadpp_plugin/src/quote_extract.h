#pragma once

#include <cstddef>
#include <string>
#include <string_view>


inline bool eaw_is_escaped(std::string_view text, std::size_t position) {
    std::size_t backslashes = 0;
    while (position > backslashes && text[position - backslashes - 1] == '\\') {
        ++backslashes;
    }
    return (backslashes % 2) != 0;
}


inline std::string eaw_unescape_quoted(std::string_view text) {
    std::string result;
    result.reserve(text.size());
    for (std::size_t index = 0; index < text.size(); ++index) {
        const char current = text[index];
        if (current == '\\' && index + 1 < text.size()) {
            const char next = text[index + 1];
            if (next == '"' || next == '\\') {
                result.push_back(next);
                ++index;
                continue;
            }
        }
        result.push_back(current);
    }
    return result;
}


inline bool eaw_is_localisation_key_character(char character) {
    return (
        (character >= 'a' && character <= 'z')
        || (character >= 'A' && character <= 'Z')
        || (character >= '0' && character <= '9')
        || character == '_'
        || character == '.'
        || character == '-'
    );
}


inline bool eaw_localisation_value_bounds(
    std::string_view line,
    std::size_t& opening_quote,
    std::size_t& closing_quote
) {
    const std::size_t colon = line.find(':');
    if (colon == std::string_view::npos) {
        return false;
    }

    std::size_t key_start = 0;
    while (key_start < colon && (line[key_start] == ' ' || line[key_start] == '\t')) {
        ++key_start;
    }
    if (key_start == colon) {
        return false;
    }
    for (std::size_t index = key_start; index < colon; ++index) {
        if (!eaw_is_localisation_key_character(line[index])) {
            return false;
        }
    }

    std::size_t index = colon + 1;
    while (index < line.size() && (line[index] == ' ' || line[index] == '\t')) {
        ++index;
    }
    while (index < line.size() && line[index] >= '0' && line[index] <= '9') {
        ++index;
    }
    while (index < line.size() && (line[index] == ' ' || line[index] == '\t')) {
        ++index;
    }
    if (index >= line.size() || line[index] != '"') {
        return false;
    }
    opening_quote = index;

    for (++index; index < line.size(); ++index) {
        if (line[index] != '"' || eaw_is_escaped(line, index)) {
            continue;
        }
        std::size_t suffix = index + 1;
        while (
            suffix < line.size()
            && (line[suffix] == ' ' || line[suffix] == '\t')
        ) {
            ++suffix;
        }
        if (suffix == line.size() || line[suffix] == '#') {
            closing_quote = index;
            return true;
        }
    }
    return false;
}


inline bool eaw_extract_quoted_value(
    std::string_view line,
    std::size_t clicked_position,
    std::string& output
) {
    std::size_t localisation_opening = 0;
    std::size_t localisation_closing = 0;
    if (
        eaw_localisation_value_bounds(
            line,
            localisation_opening,
            localisation_closing
        )
        && clicked_position >= localisation_opening
        && clicked_position <= localisation_closing
    ) {
        output = eaw_unescape_quoted(
            line.substr(
                localisation_opening + 1,
                localisation_closing - localisation_opening - 1
            )
        );
        return true;
    }

    bool inside_quotes = false;
    std::size_t opening_quote = 0;
    for (std::size_t index = 0; index < line.size(); ++index) {
        if (line[index] != '"' || eaw_is_escaped(line, index)) {
            continue;
        }
        if (!inside_quotes) {
            opening_quote = index;
            inside_quotes = true;
            continue;
        }
        if (clicked_position >= opening_quote && clicked_position <= index) {
            output = eaw_unescape_quoted(
                line.substr(opening_quote + 1, index - opening_quote - 1)
            );
            return true;
        }
        inside_quotes = false;
    }
    return false;
}
