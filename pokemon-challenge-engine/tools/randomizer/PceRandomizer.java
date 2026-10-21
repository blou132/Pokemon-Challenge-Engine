/* SPDX-License-Identifier: GPL-3.0-or-later
 * PCE adapter for the public API of Universal Pokemon Randomizer ZX 4.6.1.
 * Copyright (C) 2026 Pokemon Challenge Engine contributors.
 * Source is distributed without warranty; see COPYING in this directory.
 * ZX is a separate program, supplied by the user or a verified portable component.
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
        "wild", "starters", "trainers", "movesets", "abilities", "field_items", "evolutions", "types", "shop_items", "pickup_items"));
    // Gen I-V mythical species. ZX groups these with legendaries; a separate
    // starter filter lets the player control the two groups independently.
    static final Set<Integer> MYTHICALS = new HashSet<>(Arrays.asList(
        151, 251, 385, 386, 489, 490, 491, 492, 493, 494, 647, 648, 649));

    static boolean flag(Properties options, String name, boolean fallback) {
        String value = options.getProperty(name);
        if (value == null) return fallback;
        if (!value.equals("true") && !value.equals("false")) throw new IllegalArgumentException("Invalid flag: " + name);
        return Boolean.parseBoolean(value);
    }

    static boolean matches(Pokemon p, Properties options) {
        String type = options.getProperty("monotype_type_id");
        if (type == null) return true;
        boolean primary = p.primaryType.toString().equalsIgnoreCase(type);
        boolean secondary = p.secondaryType != null && p.secondaryType.toString().equalsIgnoreCase(type);
        switch (options.getProperty("monotype_mode")) {
            case "soft": return primary || secondary;
            case "strict": return primary;
            case "pure": return primary && (p.secondaryType == null || secondary);
            default: throw new IllegalArgumentException("Invalid Monotype mode");
        }
    }

    static boolean compatibleFuture(Pokemon p, Properties options, Set<Integer> seen) {
        if (!seen.add(p.number)) return true;
        for (Evolution e : p.evolutionsFrom) {
            if (e.type == EvolutionType.LEVEL_IS_EXTRA) continue;
            if (!matches(e.to, options) || !compatibleFuture(e.to, options, seen)) return false;
        }
        return true;
    }

    static List<Pokemon> selectStarters(RomHandler rom, Properties options, long seed) {
        List<Pokemon> preferred = new ArrayList<>(), remaining = new ArrayList<>();
        for (Pokemon p : rom.getPokemon()) {
            if (p == null || p.formeNumber != 0 || p.number > 649 || !matches(p, options)) continue;
            boolean mythical = MYTHICALS.contains(p.number);
            if (mythical && !flag(options, "starter_mythicals", true) ||
                !mythical && p.isLegendary() && !flag(options, "starter_legendaries", true)) continue;
            if (options.containsKey("monotype_type_id") && flag(options, "monotype_prefer_evolutions", true) &&
                !p.evolutionsFrom.isEmpty() && compatibleFuture(p, options, new HashSet<>())) preferred.add(p);
            else remaining.add(p);
        }
        Random random = new Random(seed ^ 0x5043455354415254L);
        Collections.shuffle(preferred, random);
        Collections.shuffle(remaining, random);
        preferred.addAll(remaining);
        if (preferred.size() < 3) throw new IllegalArgumentException("Fewer than three distinct eligible Monotype starters");
        return new ArrayList<>(preferred.subList(0, 3));
    }

    static void verifyRestrictions(RomHandler rom, Set<String> categories, Properties options) {
        if (categories.contains("starters")) {
            Set<Integer> seen = new HashSet<>();
            for (Pokemon p : rom.getStarters()) {
                boolean mythical = MYTHICALS.contains(p.number);
                if (!seen.add(p.number) || !matches(p, options) ||
                    mythical && !flag(options, "starter_mythicals", true) ||
                    !mythical && p.isLegendary() && !flag(options, "starter_legendaries", true))
                    throw new IllegalStateException("Reread starter violates selection restrictions");
            }
        }
        if (categories.contains("wild") && !flag(options, "wild_legendaries", false))
            for (EncounterSet area : rom.getEncounters(true)) for (Encounter e : area.encounters)
                if (e.pokemon.isLegendary()) throw new IllegalStateException("Reread wild legendary is forbidden");
        if (categories.contains("trainers") && !flag(options, "trainer_legendaries", false))
            for (Trainer trainer : rom.getTrainers()) for (TrainerPokemon p : trainer.pokemon)
                if (p.pokemon.isLegendary()) throw new IllegalStateException("Reread trainer legendary is forbidden");
    }

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
        rows.get("field_items").append(rom.getRegularFieldItems()).append('/').append(rom.getCurrentFieldTMs());
        for (Map.Entry<Integer, Shop> shop : new TreeMap<>(rom.getShopItems()).entrySet())
            rows.get("shop_items").append(shop.getKey()).append(':').append(shop.getValue().items).append(';');
        for (PickupItem item : rom.getPickupItems()) rows.get("pickup_items").append(item.item).append(',');
        Map<String, String> result = new LinkedHashMap<>();
        for (String key : rows.keySet()) result.put(key, digest(rows.get(key).toString()));
        return result;
    }

    static void writeReport(Path path, RomHandler rom, Map<String, String> before,
                            Map<String, String> after, String settings, int checkValue, Properties options) throws Exception {
        try (PrintWriter out = new PrintWriter(Files.newBufferedWriter(path, StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW))) {
            out.println("{\"schema_version\":2,\"tool_version\":\"" + Version.VERSION_STRING + "\",\"game_code\":\"" + rom.getROMCode() + "\",");
            out.print("\"adapter_options\":{");
            int optionIndex = 0;
            for (String key : new TreeSet<>(options.stringPropertyNames())) {
                if (!key.matches("[a-z_]+") || !options.getProperty(key).matches("[a-z0-9_]+"))
                    throw new IllegalArgumentException("Invalid adapter option");
                if (optionIndex++ > 0) out.print(',');
                out.print("\"" + key + "\":\"" + options.getProperty(key) + "\"");
            }
            out.println("},");
            out.println("\"check_value_scope\":\"zx_stage\",");
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
        if ((args.length != 7 && args.length != 8) || !"4.6.1".equals(Version.VERSION_STRING))
            throw new IllegalArgumentException("Expected pinned ZX 4.6.1 and seven or eight adapter arguments");
        Properties options = new Properties();
        if (args.length == 8) try (Reader input = Files.newBufferedReader(Paths.get(args[7]), StandardCharsets.US_ASCII)) {
            options.load(input);
        }
        Path source = Paths.get(args[0]), output = Paths.get(args[1]), report = Paths.get(args[2]);
        if (!Files.isRegularFile(source) || Files.exists(output) || Files.exists(report))
            throw new IllegalArgumentException("Input missing or output already exists");
        long seed = Long.parseLong(args[3]);
        Set<String> categories = new LinkedHashSet<>(Arrays.asList(args[4].split(",")));
        if (seed < 0 || categories.isEmpty() || !CATEGORIES.containsAll(categories))
            throw new IllegalArgumentException("Invalid seed or categories");
        if (!Arrays.asList("true", "false").contains(args[5])) throw new IllegalArgumentException("Invalid balance flag");
        boolean balanced = Boolean.parseBoolean(args[5]);
        boolean customStarters = options.containsKey("monotype_type_id") || categories.contains("starters") &&
            (!flag(options, "starter_legendaries", true) || !flag(options, "starter_mythicals", true));
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
        if (categories.contains("starters") && !customStarters) settings.setStartersMod(choice(4, 2));
        if (categories.contains("trainers")) {
            String mode = options.getProperty("trainer_mode", "random");
            int trainerChoice = Arrays.asList("random", "type_themed", "type_themed_elite4_gyms").indexOf(mode);
            if (trainerChoice < 0) throw new IllegalArgumentException("Invalid trainer mode");
            settings.setTrainersMod(choice(6, trainerChoice == 0 ? 1 : trainerChoice + 3));
        }
        if (categories.contains("movesets")) settings.setMovesetsMod(choice(4, flag(options, "movesets_same_type", false) ? 1 : 2));
        if (categories.contains("abilities")) settings.setAbilitiesMod(choice(2, 1));
        if (categories.contains("field_items")) settings.setFieldItemsMod(choice(4, 2));
        if (categories.contains("evolutions")) settings.setEvolutionsMod(choice(3, 1));
        if (categories.contains("types")) settings.setTypesMod(choice(3, flag(options, "types_follow_evolutions", false) ? 1 : 2));
        if (categories.contains("shop_items")) {
            if (!rom.hasShopRandomization()) throw new IllegalArgumentException("Shops unavailable for this ROM");
            settings.setShopItemsMod(choice(3, 2));
        }
        if (categories.contains("pickup_items")) {
            if (rom.getPickupItems().isEmpty()) throw new IllegalArgumentException("Pickup unavailable for this ROM");
            settings.setPickupItemsMod(choice(2, 1));
        }
        settings.setUseTimeBasedEncounters(true);
        if (categories.contains("wild")) {
            if (flag(options, "wild_similar_strength", balanced)) settings.setWildPokemonRestrictionMod(choice(4, 1));
            if (flag(options, "wild_type_themed", false)) settings.setWildPokemonRestrictionMod(choice(4, 3));
        }
        settings.setBlockWildLegendaries(!flag(options, "wild_legendaries", false));
        settings.setTrainersBlockLegendaries(!flag(options, "trainer_legendaries", false));
        settings.setTrainersUsePokemonOfSimilarStrength(flag(options, "trainer_similar_strength", balanced));
        settings.setEvosSimilarStrength(flag(options, "evolution_similar_strength", balanced));
        settings.setEvosSameTyping(flag(options, "evolution_same_type", false));
        settings.setEvosMaxThreeStages(flag(options, "evolution_three_stages", false));
        settings.setEvosForceChange(flag(options, "evolution_force_change", false));
        settings.tweakForRom(rom);
        String encoded = settings.toString();
        int check;
        Path randomized = customStarters ? output.resolveSibling("intermediate.nds") : output;
        if (Files.exists(randomized)) throw new IllegalArgumentException("Intermediate output exists");
        try (PrintStream log = new PrintStream(Files.newOutputStream(output.resolveSibling("randomizer.log"), StandardOpenOption.CREATE_NEW), false, "UTF-8")) {
            check = new Randomizer(settings, rom, ResourceBundle.getBundle("com/dabomstew/pkrandom/newgui/Bundle"), false).randomize(randomized.toString(), log, seed);
        }
        if (customStarters) {
            RomHandler effective = load(randomized);
            if (!effective.setStarters(selectStarters(effective, options, seed)) || !effective.saveRomFile(output.toString(), seed))
                throw new IllegalStateException("Could not persist starters");
        }
        RomHandler reread = load(output);
        if (!reread.getROMCode().equals(args[6])) throw new IllegalArgumentException("Derived identity changed");
        verifyRestrictions(reread, categories, options);
        Map<String, String> after = fingerprints(reread);
        for (String category : CATEGORIES) {
            boolean changed = !before.get(category).equals(after.get(category));
            if (categories.contains(category) != changed)
                throw new IllegalStateException("Category changed contrary to selection: " + category);
        }
        writeReport(report, reread, before, after, encoded, check, options);
        if (customStarters) Files.delete(randomized);
    }
}
