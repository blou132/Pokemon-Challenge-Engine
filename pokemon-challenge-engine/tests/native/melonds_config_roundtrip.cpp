// Exercise the same toml11 parser/serializer shipped in the pinned melonDS tree.
// No emulator, ROM, user configuration or writable disk image is opened.
#include <iostream>
#include <iterator>
#include <sstream>
#include "toml/toml.hpp"

int main()
{
    try
    {
        // toml11 expects a seekable stream; stdin is a pipe under subprocess.
        const std::string contents((std::istreambuf_iterator<char>(std::cin)), {});
        std::istringstream original(contents);
        auto config = toml::parse(original, "synthetic melonDS config");
        // Config::Table getters insert missing scalar defaults. Window.cpp reads
        // DSi.NANDPath; EmuInstance.cpp/EmuSettingsDialog.cpp read FullBIOSBoot.
        config["DSi"]["NANDPath"] = std::string{};
        config["DSi"]["FullBIOSBoot"] = false;
        std::ostringstream serialized;
        serialized << config; // same operation as Config::Save, without truncating a file
        std::istringstream input(serialized.str());
        const auto restored = toml::parse(input, "roundtrip config");
        if (toml::find<bool>(restored, "DSi", "FullBIOSBoot") ||
            toml::find<bool>(restored, "DSi", "SD", "Enable") ||
            !toml::find<std::string>(restored, "DSi", "NANDPath").empty())
            return 2;
        std::cout << "roundtrip ok\n";
        return 0;
    }
    catch (const toml::serialization_error& error)
    {
        std::cerr << error.what() << '\n';
        return 3;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
