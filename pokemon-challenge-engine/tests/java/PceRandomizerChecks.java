/* SPDX-License-Identifier: GPL-3.0-or-later
 * Synthetic algorithm checks against the real pinned ZX API, without a ROM.
 */
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
                if (method.getName().equals("getPokemon")) return pokemon;
                throw new UnsupportedOperationException(method.getName());
            });
    }
    static Properties mono(String mode) {
        Properties options = new Properties();
        options.setProperty("monotype_type_id", "fire");
        options.setProperty("monotype_mode", mode);
        return options;
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
        System.out.println("PASS: effective types, modes, evolution preference, distinctness, seed, legendary/mythical filters, insufficient pool");
    }
}
