/* SPDX-License-Identifier: GPL-3.0-or-later
 * Synthetic algorithm checks against the real pinned ZX API, without a ROM.
 */
import com.dabomstew.pkrandom.Settings;
import com.dabomstew.pkrandom.pokemon.*;
import com.dabomstew.pkrandom.romhandlers.RomHandler;
import java.lang.reflect.Proxy;
import java.util.*;

public class PceRandomizerChecks {
    static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    static Pokemon pokemon(int id, Type primary, Type secondary) {
        Pokemon p = new Pokemon();
        p.number = id;
        p.primaryType = primary;
        p.secondaryType = secondary;
        return p;
    }
    static RomHandler population(List<Pokemon> pokemon) {
        return (RomHandler) Proxy.newProxyInstance(RomHandler.class.getClassLoader(), new Class<?>[]{RomHandler.class},
            (proxy, method, args) -> {
                if (method.getName().equals("getPokemon") || method.getName().equals("getPokemonInclFormes")) return pokemon;
                if (method.getName().equals("getStarters")) return pokemon.subList(0, 3);
                throw new UnsupportedOperationException(method.getName());
            });
    }
    static Properties mono(String mode) {
        Properties options = new Properties();
        options.setProperty("monotype_type_id", "fire");
        options.setProperty("monotype_mode", mode);
        return options;
    }
    static void expectFailure(Runnable action, String message) {
        try {
            action.run();
        } catch (IllegalArgumentException | IllegalStateException expected) {
            return;
        }
        throw new AssertionError(message);
    }
    static void advancedModes() {
        Properties options = new Properties();
        Set<String> categories = new HashSet<>(Arrays.asList("wild", "trainers", "evolutions"));
        String[] wildModes = {"random", "area_mapping", "global_mapping"};
        for (int i = 0; i < wildModes.length; i++) {
            Settings settings = new Settings();
            options.setProperty("wild_mode", wildModes[i]);
            PceRandomizer.configureModes(settings, categories, options);
            require(settings.getWildPokemonMod().ordinal() == i + 1, "Actual ZX wild mode mapping");
        }
        String[] trainerModes = {"random", "distributed", "main_playthrough", "type_themed", "type_themed_elite4_gyms"};
        for (int i = 0; i < trainerModes.length; i++) {
            Settings settings = new Settings();
            options.setProperty("trainer_mode", trainerModes[i]);
            PceRandomizer.configureModes(settings, categories, options);
            require(settings.getTrainersMod().ordinal() == i + 1, "Actual ZX trainer mode mapping");
        }
        options.setProperty("evolution_mode", "unchanged");
        expectFailure(() -> PceRandomizer.configureModes(new Settings(), categories, options), "No-op evolution setting must fail");
        options.setProperty("evolution_fix_impossible", "true");
        Settings settings = new Settings();
        PceRandomizer.configureModes(settings, categories, options);
        require(settings.getEvolutionsMod() == Settings.EvolutionsMod.UNCHANGED, "Evolution targets remain unchanged");
        require(settings.isChangeImpossibleEvolutions(), "ZX corrects impossible methods");
        settings = new Settings();
        PceRandomizer.configureModes(settings, Collections.singleton("trainers"), options);
        require(!settings.isChangeImpossibleEvolutions(), "Disabled evolution category remains untouched");
        options.setProperty("wild_type_themed", "true");
        expectFailure(() -> PceRandomizer.configureModes(new Settings(), categories, options), "Global mapping must reject zone themes");
    }
    static void starterPowerAndRereadChecks() {
        List<Pokemon> species = new ArrayList<>();
        for (int id = 1; id <= 12; id++) {
            Pokemon p = pokemon(id, Type.FIRE, null);
            p.hp = id <= 3 ? 300 : id <= 6 ? 330 : 600;
            species.add(p);
        }
        Properties options = mono("pure");
        options.setProperty("starter_similar_strength", "true");
        List<Pokemon> selected = PceRandomizer.selectStarters(population(species), options, 10);
        require(selected.stream().allMatch(p -> p.hp <= 330), "Prefer candidates within ten percent of source starter BST");
        List<Pokemon> nearest = PceRandomizer.selectStarters(population(species), options, 10, Arrays.asList(900, 900, 900));
        require(nearest.stream().allMatch(p -> p.hp == 600), "Nearest BST fallback when ten percent pool is empty");
        require(new HashSet<>(nearest).size() == 3, "BST fallback remains distinct");
        List<List<Integer>> before = Arrays.asList(Arrays.asList(1, 1), Arrays.asList(1, 2));
        List<List<Integer>> area = Arrays.asList(Arrays.asList(3, 3), Arrays.asList(4, 5));
        PceRandomizer.verifyEncounterMapping(before, area, "area_mapping");
        expectFailure(() -> PceRandomizer.verifyEncounterMapping(before, area, "global_mapping"), "Detect broken global mapping after reread");
        PceRandomizer.verifyEncounterMapping(before, Arrays.asList(Arrays.asList(3, 3), Arrays.asList(3, 5)), "global_mapping");
        expectFailure(() -> PceRandomizer.verifyEncounterMapping(before, Arrays.asList(Arrays.asList(3, 4), Arrays.asList(3, 5)), "area_mapping"),
            "Detect broken local mapping after reread");
        Map<Integer, Set<Integer>> original = PceRandomizer.evolutionTargets(population(species));
        species.get(0).evolutionsFrom.add(new Evolution(species.get(0), species.get(1), true, EvolutionType.TRADE, 0));
        options.setProperty("evolution_fix_impossible", "true");
        expectFailure(() -> PceRandomizer.verifyEvolutions(population(species), original, options), "Uncorrected trade method must fail reread");
        species.get(0).evolutionsFrom.get(0).type = EvolutionType.LEVEL;
        PceRandomizer.verifyEvolutions(population(species), original, options);
        options.setProperty("evolution_mode", "unchanged");
        expectFailure(() -> PceRandomizer.verifyEvolutions(population(species), original, options), "Changed preserved target must fail reread");
        options.setProperty("evolution_mode", "random");
        species.get(1).evolutionsFrom.add(new Evolution(species.get(1), species.get(0), true, EvolutionType.LEVEL, 16));
        expectFailure(() -> PceRandomizer.verifyEvolutions(population(species), original, options), "Evolution cycle must fail reread");
    }
    public static void main(String[] args) {
        Pokemon secondary = pokemon(1, Type.GRASS, Type.FIRE);
        require(PceRandomizer.matches(secondary, mono("soft")), "Soft accepts secondary type");
        require(!PceRandomizer.matches(secondary, mono("strict")), "Strict rejects secondary type");
        Pokemon dual = pokemon(2, Type.FIRE, Type.GRASS);
        require(PceRandomizer.matches(dual, mono("strict")), "Strict accepts primary type");
        require(!PceRandomizer.matches(dual, mono("pure")), "Pure rejects dual type");
        List<Pokemon> species = new ArrayList<>();
        for (int id = 1; id <= 12; id++) species.add(pokemon(id, Type.FIRE, null));
        // These effective types intentionally disagree with the real species:
        // selection must use the transformed structures, not a stock database.
        for (int id = 0; id < 3; id++) species.get(id).evolutionsFrom.add(
            new Evolution(species.get(id), species.get(id + 3), true, EvolutionType.LEVEL, 16));
        species.get(6).evolutionsFrom.add(new Evolution(species.get(6), secondary, true, EvolutionType.LEVEL, 20));
        RomHandler rom = population(species);
        List<Pokemon> first = PceRandomizer.selectStarters(rom, mono("pure"), 512);
        require(new HashSet<>(first).size() == 3, "Three distinct starters");
        require(first.equals(PceRandomizer.selectStarters(rom, mono("pure"), 512)), "Seed reproducible");
        require(first.stream().allMatch(p -> p.number <= 3), "Compatible future evolutions preferred");
        Set<List<Pokemon>> draws = new HashSet<>();
        for (int seed = 0; seed < 20; seed++) draws.add(PceRandomizer.selectStarters(rom, mono("pure"), seed));
        require(draws.size() > 1, "Seed controls selection order");
        Pokemon mythical = pokemon(151, Type.FIRE, null), legendary = pokemon(150, Type.FIRE, null);
        species.add(mythical);
        species.add(legendary);
        Properties noLegendary = mono("pure");
        noLegendary.setProperty("monotype_prefer_evolutions", "false");
        noLegendary.setProperty("starter_legendaries", "false");
        noLegendary.setProperty("starter_mythicals", "true");
        boolean sawMythical = false;
        for (int seed = 0; seed < 100; seed++) {
            List<Pokemon> chosen = PceRandomizer.selectStarters(rom, noLegendary, seed);
            require(!chosen.contains(legendary), "Legendary exclusion");
            sawMythical |= chosen.contains(mythical);
        }
        require(sawMythical, "Mythical permission independent of legendary exclusion");
        noLegendary.setProperty("starter_mythicals", "false");
        for (int seed = 0; seed < 100; seed++)
            require(!PceRandomizer.selectStarters(rom, noLegendary, seed).contains(mythical), "Mythical exclusion");
        try {
            PceRandomizer.selectStarters(population(species.subList(0, 2)), mono("pure"), 512);
            throw new AssertionError("Insufficient population must fail");
        } catch (IllegalArgumentException expected) {
            require(expected.getMessage().contains("three"), "Explicit insufficient-population error");
        }
        List<PickupItem> pickup = Arrays.asList(new PickupItem(1), new PickupItem(2));
        PceRandomizer.verifyPickupItems(pickup, Arrays.asList(new PickupItem(1), new PickupItem(2)));
        expectFailure(() -> PceRandomizer.verifyPickupItems(pickup, Collections.emptyList()), "Missing reread Pickup table must fail");
        expectFailure(() -> PceRandomizer.verifyPickupItems(pickup, Arrays.asList(new PickupItem(1), new PickupItem(3))),
            "Incorrect reread Pickup item must fail");
        advancedModes();
        starterPowerAndRereadChecks();
        System.out.println("PASS: persisted Pickup table, ZX modes, starter strength, reread mappings, evolution cycles/methods/targets; effective types, modes, evolution preference, distinctness, seed, legendary/mythical filters, insufficient pool");
    }
}
