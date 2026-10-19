/* SPDX-License-Identifier: GPL-3.0-or-later
 * PCE adapter for the public API of Universal Pokemon Randomizer ZX 4.6.1.
 * Copyright (C) 2026 Pokemon Challenge Engine contributors.
 * Source is distributed without warranty; see COPYING in this directory.
 * ZX itself is an external user-supplied program, never bundled with PCE.
 */
import com.dabomstew.pkrandom.FileFunctions;
import com.dabomstew.pkrandom.RandomSource;
import com.dabomstew.pkrandom.Randomizer;
import com.dabomstew.pkrandom.Settings;
import com.dabomstew.pkrandom.Version;
import com.dabomstew.pkrandom.pokemon.*;
import com.dabomstew.pkrandom.romhandlers.Gen5RomHandler;
import com.dabomstew.pkrandom.romhandlers.RomHandler;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

public class PceRandomizer {
    static final Set<String> CATEGORIES = new LinkedHashSet<>(Arrays.asList(
        "wild", "starters", "trainers", "movesets", "abilities", "field_items", "evolutions", "types"));

    static boolean[] choice(int count, int selected) {
        boolean[] result = new boolean[count];
        result[selected] = true;
        return result;
    }

    static RomHandler load(Path path) {
        Gen5RomHandler.Factory factory = new Gen5RomHandler.Factory();
        if (!factory.isLoadable(path.toString())) throw new IllegalArgumentException("Unsupported Gen V ROM");
        RomHandler rom = factory.create(RandomSource.instance());
        if (!rom.loadRom(path.toString())) throw new IllegalArgumentException("Cannot load ROM");
        return rom;
    }

    static String digest(String text) throws Exception {
        byte[] bytes = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
        StringBuilder result = new StringBuilder();
        for (byte b : bytes) result.append(String.format(Locale.ROOT, "%02x", b & 255));
        return result.toString();
    }

    // Fingerprints are computed from reread structures, never from an operation's success message.
    static Map<String, String> fingerprints(RomHandler rom) throws Exception {
        Map<String, StringBuilder> rows = new LinkedHashMap<>();
        for (String name : CATEGORIES) rows.put(name, new StringBuilder());
        for (Pokemon p : rom.getStarters()) rows.get("starters").append(p.number).append(',');
        for (EncounterSet area : rom.getEncounters(true))
            for (Encounter e : area.encounters) rows.get("wild").append(e.pokemon.number).append(',');
        for (Trainer t : rom.getTrainers())
            for (TrainerPokemon p : t.pokemon) rows.get("trainers").append(p.pokemon.number).append(',');
        for (Map.Entry<Integer, List<MoveLearnt>> entry : new TreeMap<>(rom.getMovesLearnt()).entrySet()) {
            rows.get("movesets").append(entry.getKey()).append(':');
            for (MoveLearnt move : entry.getValue()) rows.get("movesets").append(move.level).append('/').append(move.move).append(',');
        }
        for (Pokemon p : rom.getPokemonInclFormes()) {
            if (p == null) continue;
            rows.get("abilities").append(p.number).append(':').append(p.ability1).append('/').append(p.ability2).append('/').append(p.ability3).append(',');
            rows.get("types").append(p.number).append(':').append(p.primaryType).append('/').append(p.secondaryType).append(',');
            rows.get("evolutions").append(p.number).append(':');
            for (Evolution e : p.evolutionsFrom) rows.get("evolutions").append(e.to.number).append('/').append(e.type).append('/').append(e.extraInfo).append(',');
        }
        rows.get("field_items").append(rom.getRegularFieldItems());
        Map<String, String> result = new LinkedHashMap<>();
        for (String key : rows.keySet()) result.put(key, digest(rows.get(key).toString()));
        return result;
    }

    static void writeReport(Path path, RomHandler rom, Map<String, String> before,
                            Map<String, String> after, String settings, int checkValue) throws Exception {
        try (PrintWriter out = new PrintWriter(Files.newBufferedWriter(path, StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW))) {
            out.println("{\"schema_version\":1,\"tool_version\":\"" + Version.VERSION_STRING + "\",\"game_code\":\"" + rom.getROMCode() + "\",");
            out.println("\"settings_string\":\"" + Version.VERSION + settings + "\",\"check_value\":" + checkValue + ",\"categories\":{");
            int n = 0;
            for (String key : CATEGORIES) {
                if (n++ > 0) out.println(',');
                out.print("\"" + key + "\":{\"before\":\"" + before.get(key) + "\",\"after\":\"" + after.get(key) + "\"}");
            }
            out.println("},\"starters\":[");
            n = 0;
            for (Pokemon p : rom.getStarters()) {
                if (n++ > 0) out.print(',');
                out.print(p.number);
            }
            out.println("],\"pokemon\":[");
            n = 0;
            for (Pokemon p : rom.getPokemonInclFormes()) {
                if (p == null) continue;
                if (n++ > 0) out.println(',');
                int species = p.baseForme == null ? p.number : p.baseForme.number;
                out.print("{\"species_id\":" + species + ",\"form\":" + p.formeNumber + ",\"types\":[\"" + p.primaryType.toString().toLowerCase(Locale.ROOT) + "\"");
                if (p.secondaryType != null && p.secondaryType != p.primaryType)
                    out.print(",\"" + p.secondaryType.toString().toLowerCase(Locale.ROOT) + "\"");
                out.print("],\"evolutions\":[");
                int evo = 0;
                for (Evolution e : p.evolutionsFrom) {
                    if (evo++ > 0) out.print(',');
                    out.print(e.to.baseForme == null ? e.to.number : e.to.baseForme.number);
                }
                out.print("],\"identity_evolutions\":[");
                evo = 0;
                for (Evolution e : p.evolutionsFrom) {
                    // Gen V index 15 creates the extra individual (Shedinja).
                    // Index 14/LEVEL_CREATE_EXTRA is the main Ninjask evolution.
                    if (e.type == EvolutionType.LEVEL_IS_EXTRA) continue;
                    if (evo++ > 0) out.print(',');
                    out.print(e.to.baseForme == null ? e.to.number : e.to.baseForme.number);
                }
                out.print("],\"evolution_conditions\":[");
                evo = 0;
                for (Evolution e : p.evolutionsFrom) {
                    if (evo++ > 0) out.print(',');
                    int target = e.to.baseForme == null ? e.to.number : e.to.baseForme.number;
                    out.print("{\"species_id\":" + target + ",\"form\":" + e.to.formeNumber
                        + ",\"method\":\"" + e.type.name() + "\",\"parameter\":" + e.extraInfo + "}");
                }
                out.print("]}");
            }
            out.println("]}");
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 7 || !"4.6.1".equals(Version.VERSION_STRING))
            throw new IllegalArgumentException("Expected pinned ZX 4.6.1 and seven adapter arguments");
        Path source = Paths.get(args[0]), output = Paths.get(args[1]), report = Paths.get(args[2]);
        if (!Files.isRegularFile(source) || Files.exists(output) || Files.exists(report))
            throw new IllegalArgumentException("Input missing or output already exists");
        long seed = Long.parseLong(args[3]);
        Set<String> categories = new LinkedHashSet<>(Arrays.asList(args[4].split(",")));
        if (seed < 0 || categories.isEmpty() || !CATEGORIES.containsAll(categories))
            throw new IllegalArgumentException("Invalid seed or categories");
        if (!Arrays.asList("true", "false").contains(args[5])) throw new IllegalArgumentException("Invalid balance flag");
        boolean balanced = Boolean.parseBoolean(args[5]);
        RomHandler rom = load(source);
        if (!rom.isRomValid()) throw new IllegalArgumentException("Source does not match ZX clean-ROM CRCs");
        if (!args[6].equals(rom.getROMCode())) throw new IllegalArgumentException("Unexpected game code");
        Map<String, String> before = fingerprints(rom);
        Settings settings = new Settings();
        settings.setCustomNames(FileFunctions.getCustomNames());
        settings.setRomName(rom.getROMName());
        // Serialized even when EXP normalization is disabled in Settings.
        settings.setSelectedEXPCurve(ExpCurve.MEDIUM_FAST);
        settings.setCustomStarters(rom.getStarters().stream().mapToInt(p -> p.number).toArray());
        if (categories.contains("wild")) settings.setWildPokemonMod(choice(4, 1));
        if (categories.contains("starters")) settings.setStartersMod(choice(4, 2));
        if (categories.contains("trainers")) settings.setTrainersMod(choice(6, 1));
        if (categories.contains("movesets")) settings.setMovesetsMod(choice(4, 2));
        if (categories.contains("abilities")) settings.setAbilitiesMod(choice(2, 1));
        if (categories.contains("field_items")) settings.setFieldItemsMod(choice(4, 2));
        if (categories.contains("evolutions")) settings.setEvolutionsMod(choice(3, 1));
        if (categories.contains("types")) settings.setTypesMod(choice(3, 2));
        settings.setUseTimeBasedEncounters(true);
        if (balanced && categories.contains("wild")) settings.setWildPokemonRestrictionMod(choice(4, 1));
        settings.setTrainersUsePokemonOfSimilarStrength(balanced);
        settings.setEvosSimilarStrength(balanced);
        settings.tweakForRom(rom);
        String encoded = settings.toString();
        int check;
        try (PrintStream log = new PrintStream(Files.newOutputStream(output.resolveSibling("randomizer.log"), StandardOpenOption.CREATE_NEW), false, "UTF-8")) {
            check = new Randomizer(settings, rom, ResourceBundle.getBundle("com/dabomstew/pkrandom/newgui/Bundle"), false).randomize(output.toString(), log, seed);
        }
        RomHandler reread = load(output);
        if (!reread.getROMCode().equals(args[6])) throw new IllegalArgumentException("Derived identity changed");
        Map<String, String> after = fingerprints(reread);
        for (String category : CATEGORIES) {
            boolean changed = !before.get(category).equals(after.get(category));
            if (categories.contains(category) != changed)
                throw new IllegalStateException("Category changed contrary to selection: " + category);
        }
        writeReport(report, reread, before, after, encoded, check);
    }
}
