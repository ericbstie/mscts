# What decides the order of the recipe book's buttons? — 2026-10-22

Evidence for #438. Since #363 the Comparison numbers recipe display ids again per Transcript
and sorts a `recipe_book_add`'s entries by what they show, so a server's own ids and entry
order no longer make a Divergence. The question is whether the order in which the 26.3 client
lays out the recipe book's buttons follows from the display ids alone, so that a derived
order could be compared. Facts are **verified** with `scripts/research/javap.py` on the 26.3
client jar, and with a Java 25 program (`ButtonOrder.java`, below) for what `java.util.HashMap`
does with these keys, as each line says.

## Answer

The order follows from the ids **and** from the book's history since the join: how many
recipes it has held at once, and the order in which ids that share a bucket were added. The
client sorts nothing. Two servers that send the same recipes under the same ids can show the
buttons in different orders, and two that send them under different ids can show the same
order.

## The client's path (javap)

- `ClientRecipeBook.<init>`: `known = new HashMap()` (the default table: 16 buckets, load
  factor 0.75), keyed by `RecipeDisplayId`.
- `ClientRecipeBook.add`: `known.put(entry.id(), entry)`. `remove`: `known.remove(id)` and
  `highlight.remove(id)`. `clear`: `known.clear()` and `highlight.clear()`.
- `ClientPacketListener.handleRecipeBookAdd`: if `replace()`, `book.clear()`; then for each of
  `entries()` in order, `book.add(contents)` (and the highlight and toast); then
  `refreshRecipeBook`, which calls `rebuildCollections`. `handleRecipeBookRemove` calls
  `book.remove` for each of `recipes()` in order, then `refreshRecipeBook`.
- `ClientRecipeBook.rebuildCollections` passes `known.values()` to
  `categorizeAndGroupRecipes`, then builds each search tab by concatenating the lists of
  `SearchRecipeBookCategory.includedCategories()` in that list's order.
- `ClientRecipeBook.categorizeAndGroupRecipes` walks the entries in iteration order. An entry
  with no group becomes a list of its own, appended to its category's list. An entry with a
  group goes into the `HashBasedTable` list for (category, group); that list is appended to
  the category's list when its first entry is seen. So a button's place, and the order of the
  recipes inside a grouped button, follow the iteration order of `known`.
- `RecipeBookComponent.updateCollections(boolean, boolean)` copies the tab's list
  (`Lists.newArrayList`) and only removes from it: collections with nothing selected, those
  not in the search results (an `ObjectLinkedOpenHashSet`, used for membership only), and,
  when filtering, those with nothing craftable. It then calls `RecipeBookPage.updateCollections`.
- `RecipeBookPage.updateCollections` keeps the list and sets `totalPages` to
  `ceil(size / 20)`. `updateButtonsForPage` gives button `i` of page `p` the collection at
  `20 * p + i`. Neither class sorts.
- `RecipeDisplayId` is a record with one `int` field, `index`; its `hashCode` is the record's
  `ObjectMethods` bootstrap.
- `ClientPacketListener.handleLogin` creates `new ClientRecipeBook()` and passes it to
  `MultiPlayerGameMode.createPlayer`. `handleRespawn` passes the old player's
  `getRecipeBook()` on both of its paths. So one book, and one `HashMap` table, lasts from a
  login to the next.

## What the `HashMap` does with these keys (Java 25, verified)

`ButtonOrder.java` (at the end of this note) puts a one-`int` record into a `HashMap`, as the
client does, and prints the iteration order. Run from the checkout with
`mise exec -- java /abs/path/ButtonOrder.java` (`java 25.0.4.1+1-LTS`):

| Case | Order |
| --- | --- |
| `hashCode` of ids 0, 1, 5, 16, 17, 1000, 65537, −3 | the id itself |
| put 1 then 17 (both in bucket 1 of 16) | `[1, 17]` |
| put 17 then 1 | `[17, 1]` |
| put 5 and 16 into a new map | `[16, 5]` |
| put 5 and 16, plus 11 more ids that are then removed (the table grew to 32) | `[5, 16]` |
| the same grown map, cleared, then 5 and 16 put again | `[5, 16]` |
| ids 0 to 1499 put in descending order | ascending |

So the iteration order is by bucket, the id modulo the table size, and within a bucket by
the order the ids were put. The table doubles when the map holds more than three quarters of
it and never shrinks: not on `remove`, and not on `clear`, which a `replace` calls. Once the
table is larger than every id, the order is ascending by id.

## What this means for the Comparison

All three inputs (the ids, the most recipes held since the login, and the put order of ids
that share a bucket) reach the Bot in `recipe_book_add` and `recipe_book_remove`, but none
of them survives the Comparison's canonical form: the ids are numbered again and the entries
sorted. A derived order would need a model of the client's `HashMap` replayed over each
server's packets from the login, raw ids and entry order included. #438 names the limit in
`docs/reference/test-cases.md` and `docs/reference/groups.md` instead.

## `ButtonOrder.java`

Its output, in the order of the table above: `hashCode(i) = i` for each id; `[1, 17]`;
`[17, 1]`; `[16, 5]`; `[5, 16]`; `[5, 16]`; `true`.

```java
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Iteration order of a HashMap keyed by a one-int record, as ClientRecipeBook.known is. */
public class ButtonOrder {
    record RecipeDisplayId(int index) {}

    static List<Integer> order(Map<RecipeDisplayId, String> known) {
        return known.keySet().stream().map(RecipeDisplayId::index).toList();
    }

    static Map<RecipeDisplayId, String> book(int... ids) {
        Map<RecipeDisplayId, String> known = new HashMap<>();
        for (int id : ids) {
            known.put(new RecipeDisplayId(id), "r" + id);
        }
        return known;
    }

    public static void main(String[] args) {
        System.out.println("java " + Runtime.version());
        for (int i : new int[] {0, 1, 5, 16, 17, 1000, 65537, -3}) {
            System.out.println("hashCode(" + i + ") = " + new RecipeDisplayId(i).hashCode());
        }

        // 1. Same ids, same history except insertion order: ids 1 and 17 share bucket 1 of 16.
        System.out.println("A put 1,17 -> " + order(book(1, 17)));
        System.out.println("B put 17,1 -> " + order(book(17, 1)));

        // 2. Same final ids {5, 16}, but one book once held 13 recipes (table grew to 32).
        Map<RecipeDisplayId, String> fresh = book(5, 16);
        Map<RecipeDisplayId, String> grown = book(5, 16);
        for (int id = 100; id < 111; id++) {
            grown.put(new RecipeDisplayId(id), "x");
        }
        for (int id = 100; id < 111; id++) {
            grown.remove(new RecipeDisplayId(id));
        }
        System.out.println("C fresh {5,16} -> " + order(fresh));
        System.out.println("D grown {5,16} -> " + order(grown));

        // 3. clear() (a replace) keeps the grown table.
        grown.clear();
        grown.put(new RecipeDisplayId(5), "r5");
        grown.put(new RecipeDisplayId(16), "r16");
        System.out.println("E grown, cleared, {5,16} -> " + order(grown));

        // 4. Once the table is larger than every id, the order is ascending by id.
        Map<RecipeDisplayId, String> big = book();
        for (int id = 1499; id >= 0; id--) {
            big.put(new RecipeDisplayId(id), "r" + id);
        }
        List<Integer> bigOrder = order(big);
        boolean ascending = true;
        for (int i = 1; i < bigOrder.size(); i++) {
            ascending &= bigOrder.get(i - 1) < bigOrder.get(i);
        }
        System.out.println("F 1500 ids put descending, ascending iteration: " + ascending);
    }
}
```
