#include "../src/quote_extract.h"

#include <cassert>
#include <string>


int main() {
    std::string output;

    const std::string localisation =
        u8R"(BAL_focus_desc:0 "Армия: §Y+5%§! Attack")";
    assert(eaw_extract_quoted_value(localisation, 29, output));
    assert(output == u8"Армия: §Y+5%§! Attack");

    output.clear();
    const std::string escaped = R"(key:0 "Текст \"в кавычках\" и \n перенос")";
    assert(eaw_extract_quoted_value(escaped, 12, output));
    assert(output == R"(Текст "в кавычках" и \n перенос)");

    output.clear();
    const std::string multiple = R"(one "первый" two "второй")";
    const std::size_t second_value = multiple.find(u8"второй");
    assert(second_value != std::string::npos);
    assert(eaw_extract_quoted_value(multiple, second_value, output));
    assert(output == u8"второй");

    output.clear();
    const std::string false_quotes =
        u8R"(ABY_focus_desc:0 "Вот уже около века абиссинский пурр привязан к золотому стандарту, который "финансирует" [Root.ABY_royal_loc_nocap]ая казна. К сожалению, недавний займ привёл к инфляции.")";
    const std::size_t inner_word = false_quotes.find(u8"финансирует");
    assert(inner_word != std::string::npos);
    assert(eaw_extract_quoted_value(false_quotes, inner_word, output));
    assert(
        output
        == u8R"(Вот уже около века абиссинский пурр привязан к золотому стандарту, который "финансирует" [Root.ABY_royal_loc_nocap]ая казна. К сожалению, недавний займ привёл к инфляции.)"
    );

    output.clear();
    assert(!eaw_extract_quoted_value(localisation, 2, output));
    assert(!eaw_extract_quoted_value("key:0 no quotes", 8, output));
    return 0;
}
