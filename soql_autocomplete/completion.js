// Lexer offsets are UTF-16 offsets, matching textarea.selectionStart.
const AGGREGATES = ["AVG", "COUNT", "COUNT_DISTINCT", "MAX", "MIN", "SUM"];
const NUMERIC = new Set(["int", "long", "double", "currency", "percent"]);
const DATES = ["YESTERDAY", "TODAY", "TOMORROW", "LAST_90_DAYS", "NEXT_90_DAYS"];
for (const unit of ["WEEK", "MONTH", "QUARTER", "YEAR", "FISCAL_QUARTER", "FISCAL_YEAR"]) {
  for (const span of ["LAST", "THIS", "NEXT"]) DATES.push(span + "_" + unit);
}
for (const unit of ["DAYS", "WEEKS", "MONTHS", "QUARTERS", "YEARS", "FISCAL_QUARTERS", "FISCAL_YEARS"]) {
  for (const span of ["LAST", "NEXT"]) DATES.push(span + "_N_" + unit + ":1");
}

function lex(text) {
  const pattern = /'(?:\\[\s\S]|[^'\\])*(?:'|\\?$)|[a-zA-Z_][\w]*|\d{4}-\d\d-\d\d(?:T[\d:.+Z-]+)?|\d+(?:\.\d+)?|!=|<=|>=|<>|[^\s]/gi;
  return Array.from(text.matchAll(pattern), m => ({
    word: m[0].toUpperCase(), raw: m[0], start: m.index, end: m.index + m[0].length,
  }));
}

function named(map, key) {
  return map && key ? map.get(key.toUpperCase()) : undefined;
}

function keyed(obj) {
  return new Map(Object.entries(obj).map(([name, value]) => [name.toUpperCase(), {name, value}]));
}

class SchemaIndex {
  constructor(objects) {
    this.objects = new Map(objects.map(n => [n.toUpperCase(), n]));
    this.schema = new Map();
  }
  add(batch) {
    for (const [name, {fields, parents, children}] of Object.entries(batch)) {
      const byName = keyed(fields);
      this.schema.set(name, {fields: byName, parents: keyed(parents), children: keyed(children)});
    }
  }
}

// Keep independent SELECT scopes. Parent expressions see a subquery as a pair
// of parentheses, not as a second FROM or WHERE belonging to the parent.
function queryScopes(tokens, caret, index) {
  const root = {tokens: [], parent: null, level: 0};
  let current = root, active = root;
  const stack = [];
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (t.word === ")") {
      const outer = stack.pop();
      if (outer && current !== outer) current = outer;
      current.level = Math.max(0, current.level - 1);
    }
    const previous = current.tokens.at(-1);
    const topKeyword = !current.level && CLAUSES.includes(t.word) &&
      previous?.clause !== "FROM" && previous?.word !== ".";
    current.tokens.push({...t, level: current.level, clause: topKeyword ? t.word : null});
    if (t.word === "(") {
      stack.push(current);
      current.level++;
      if (tokens[i + 1]?.word === "SELECT") {
        const prev = current.tokens.at(-2)?.word;
        current = {tokens: [], parent: current, child: prev !== "IN", level: 0};
      }
    }
    if (t.end <= caret) active = current;
  }
  const needs = new Set();
  function source(scope) {
    const from = scope.tokens.findIndex(t => t.clause === "FROM");
    const token = scope.tokens[from + 1];
    const raw = from >= 0 && token && scope.tokens[from + 2]?.word !== "." ? token.word : null;
    const parentName = scope.child ? source(scope.parent).name : null;
    const parent = parentName && index.schema.get(parentName);
    if (parentName && !parent && from >= 0) needs.add(parentName);
    const name = scope.child ? named(parent?.children, raw)?.value : named(index.objects, raw);
    const next = from < 0 ? null : scope.tokens[from + 2];
    const alias = next && !next.clause && /^[A-Z_]/.test(next.word) ? next.word : null;
    return {name, parent, alias};
  }
  return {scope: active, ...source(active), needs};
}

const CLAUSES = ["SELECT", "FROM", "WHERE", "WITH", "GROUP", "HAVING", "ORDER", "LIMIT", "OFFSET", "FOR"];
function complete(text, caret, index) {
  const tokens = lex(text);
  const items = [], seen = new Set();
  const result = {items, start: caret, end: caret, needs: [], space: ""};
  const literal = tokens.find(t => t.raw.startsWith("'") && t.start < caret &&
    (caret < t.end || (caret === t.end && !/^'(?:\\[\s\S]|[^'\\])*'$/.test(t.raw))));
  if (literal) return result;
  const {scope, name, parent, alias, needs} = queryScopes(tokens, caret, index);
  let token = scope.tokens.find(t => /^[A-Z_]/.test(t.word) && t.start <= caret && caret <= t.end);
  // FROM immediately opens its object list, even before the first space.
  if (token?.word === "FROM" && caret === token.end) {
    result.space = " ";
    token = null;
  }
  result.start = token?.start ?? caret;
  result.end = token?.end ?? caret;
  const prefix = text.slice(result.start, caret).toUpperCase();
  const before = scope.tokens.filter(t => t.end <= result.start);
  const after = scope.tokens.filter(t => t.start >= result.end);
  const last = before.at(-1)?.word, prev = before.at(-2)?.word;
  const clauseToken = before.findLast(t => t.clause);
  const clause = clauseToken?.word;
  const top = scope.tokens.filter(t => !t.level);
  const has = kw => top.some(t => t.clause === kw);
  const schema = index.schema.get(name);
  const semiJoin = scope.parent && !scope.child;
  const aggregate = top.some((t, i) => AGGREGATES.includes(t.word) && top[i + 1]?.word === "(");

  function add(label, kind, insert = label) {
    const key = label.toUpperCase();
    if (!key.startsWith(prefix) || seen.has(kind + key)) return;
    seen.add(kind + key);
    items.push({label, kind, insert});
  }
  function words(list) { for (const word of list) add(word, "Keyword"); }
  function functions() { for (const fn of AGGREGATES) add(fn + "()", "Function"); }
  function fieldSource() {
    let source = schema;
    if (name && !source) needs.add(name);
    if (last !== ".") return source;
    const path = [];
    for (let i = before.length - 1; i > 0 && before[i].word === "."; i -= 2) {
      path.unshift(before[i - 1].word);
    }
    if (path[0] === name?.toUpperCase() || path[0] === alias) path.shift();
    for (const part of path) {
      const target = named(source?.parents, part)?.value;
      if (!target) return null;
      source = index.schema.get(target);
      if (!source) needs.add(target);
    }
    return source;
  }
  function fields(flag = "", func = null) {
    const source = fieldSource();
    if (!source) return;
    for (const field of source.fields.values()) {
      const [type, flags] = field.value;
      if (!flags.includes(flag) || (["SUM", "AVG"].includes(func) && !NUMERIC.has(type))) continue;
      if ((clause === "HAVING" || (clause === "ORDER" && aggregate && has("GROUP"))) &&
          !func && !groupFields.has(field.name.toUpperCase())) continue;
      add(field.name, "Field");
    }
    if (!func && clause !== "HAVING") {
      for (const rel of source.parents.values()) add(rel.name, "Relationship", rel.name + ".");
    }
  }
  const groupStart = top.findIndex(t => t.clause === "GROUP");
  const groupFields = new Set();
  if (groupStart >= 0) {
    for (const t of top.slice(groupStart + 2)) {
      if (t.clause) break;
      groupFields.add(t.word);
    }
  }
  function clauses() {
    // Enforce clause order on both sides when editing a query in the middle.
    const next = after.find(t => t.clause);
    const lo = CLAUSES.indexOf(clause), hi = next ? CLAUSES.indexOf(next.word) : CLAUSES.length;
    for (const kw of ["WHERE", "WITH", "GROUP", "HAVING", "ORDER", "LIMIT", "OFFSET"]) {
      const pos = CLAUSES.indexOf(kw);
      if (pos <= lo || pos >= hi || (has(kw) && token?.word !== kw)) continue;
      if (kw === "HAVING" && !has("GROUP")) continue;
      if (semiJoin && kw !== "WHERE") continue;
      if (scope.child && ["HAVING", "GROUP", "WITH", "OFFSET"].includes(kw)) continue;
      if (kw === "WITH" && !supportsWith()) continue;
      words([kw === "ORDER" || kw === "GROUP" ? kw + " BY" : kw]);
    }
    // FOR UPDATE is Apex-only. This page executes through Salesforce REST.
  }
  function supportsWith() {
    return /(?:__KAV|^KNOWLEDGEARTICLEVERSION$|^QUESTION$|^USERPROFILEFEED$)/i.test(name || "");
  }
  function pathType(i) {
    let source = schema;
    const path = [];
    for (let p = i - 1; p >= 1 && before[p].word === "."; p -= 2) path.unshift(before[p-1].word);
    if (path[0] === name?.toUpperCase() || path[0] === alias) path.shift();
    for (const rel of path) {
      const target = named(source?.parents, rel)?.value;
      source = index.schema.get(target);
      if (target && !source) needs.add(target);
    }
    return named(source?.fields, before[i]?.word)?.value[0];
  }
  function valueType() {
    const op = before.findLastIndex(t => /^(?:[=!<>]+|IN|LIKE|INCLUDES|EXCLUDES)$/.test(t.word));
    let i = op - 1;
    if (before[i]?.word === "NOT") i--;
    if (before[i]?.word === ")") {
      const fn = before[i - 3]?.word;
      if (["COUNT", "COUNT_DISTINCT", "SUM", "AVG"].includes(fn)) return "double";
      i--;
    }
    return pathType(i);
  }
  function literals(op) {
    const type = valueType();
    if (["LIKE", "INCLUDES", "EXCLUDES"].includes(op)) return;
    if (["=", "!=", "<>", "IN"].includes(op)) {
      add("NULL", "Literal");
      if (type === "boolean") for (const word of ["FALSE", "TRUE"]) add(word, "Literal");
    }
    if (["date", "datetime"].includes(type)) for (const word of DATES) add(word, "Date");
  }

  // Match the innermost still-open parenthesis (a function, condition, or list).
  const opens = [];
  for (let i = 0; i < before.length; i++) {
    if (before[i].word === "(") opens.push(i);
    else if (before[i].word === ")") opens.pop();
  }
  const open = opens.at(-1);
  const enclosing = open === undefined ? null : before[open - 1]?.word;
  const inFunction = AGGREGATES.includes(enclosing);
  const inList = ["IN", "INCLUDES", "EXCLUDES"].includes(enclosing);
  if (!clause) {
    words(["SELECT"]);
  } else if (inFunction && ["(", "."].includes(last)) {
    fields(enclosing === "COUNT" ? "" : "a", enclosing);
  } else if (inList) {
    if (["(", ","].includes(last)) {
      literals(enclosing);
      if (last === "(" && enclosing === "IN" && ["id", "reference"].includes(valueType())) words(["SELECT"]);
    }
  } else if (clause === "SELECT") {
    if (["SELECT", ",", "."].includes(last)) {
      fields();
      if (last !== "." && !scope.parent) functions();
    } else if (last === "(" && !inFunction) words(["SELECT"]);
    else if (!opens.length && (!has("FROM") || token?.word === "FROM")) words(["FROM"]);
  } else if (clause === "FROM" && last === "FROM") {
    const options = scope.child ? Array.from(parent?.children.values() || [], r => r.name) : index.objects.values();
    for (const object of options) add(object, "Object");
  } else if (["GROUP", "ORDER"].includes(clause) && last === clause) {
    words(["BY"]);
  } else if (clause === "WHERE" || clause === "HAVING") {
    if (name && !schema) needs.add(name);
    if ([clause, "AND", "OR", "(", "."].includes(last) || (last === "NOT" && [clause, "AND", "OR", "("].includes(prev))) {
      fields(clause === "WHERE" ? "f" : "g");
      if (last !== "." && last !== "NOT") words(["NOT"]);
      if (clause === "HAVING" && last !== ".") functions();
    } else if (last === "NOT") {
      words(["IN"]);
    } else if (/^(?:[=!<>]+|LIKE)$/.test(last)) {
      literals(last);
    } else if (["IN", "INCLUDES", "EXCLUDES"].includes(last)) {
      // These operators require a parenthesized list or subquery.
    } else {
      const lhsType = pathType(before.length - 1);
      const isLhs = lhsType || (last === ")" &&
        before.slice(0, -1).findLast(t => t.word === "(") &&
        AGGREGATES.includes(before[before.findLastIndex(t => t.word === "(") - 1]?.word));
      const isValue = last?.startsWith("'") || /^\d/.test(last) ||
        ["TRUE", "FALSE", "NULL", ")"].includes(last) || DATES.includes(last);
      if (isLhs && !/^[=!<>]+$/.test(prev || "")) {
        const type = lhsType;
        for (const op of ["=", "!="]) add(op, "Operator");
        if (NUMERIC.has(type) || ["date", "datetime"].includes(type) || !type)
          for (const op of ["<", "<=", ">", ">="]) add(op, "Operator");
        if (type === "multipicklist") words(["INCLUDES", "EXCLUDES"]);
        else {
          words(["IN", "NOT IN"]);
          if (["string", "email", "phone", "url", "textarea"].includes(type)) words(["LIKE"]);
        }
      } else if (isValue && !inFunction) {
        words(["AND", "OR"]);
        if (!opens.length) clauses();
      }
    }
  } else if (clause === "ORDER" || clause === "GROUP") {
    if (["BY", ",", "."].includes(last)) {
      fields(clause === "ORDER" ? "s" : "g");
      if (clause === "ORDER" && last !== "." && has("GROUP")) functions();
    }
    else if (last === "NULLS") words(["FIRST", "LAST"]);
    else {
      if (clause === "ORDER" && !["FIRST", "LAST"].includes(last)) {
        if (!["ASC", "DESC"].includes(last)) words(["ASC", "DESC"]);
        words(["NULLS FIRST", "NULLS LAST"]);
      }
      clauses();
    }
  } else if (clause === "WITH" && last === "WITH") {
    if (name && !schema) needs.add(name);
    if (supportsWith() && name.toUpperCase() !== "USERPROFILEFEED") words(["DATA CATEGORY"]);
    if (name?.toUpperCase() === "USERPROFILEFEED") {
      const userField = named(schema?.fields, "USERID");
      if (userField) add(userField.name, "Field");
    }
  } else if (clause === "WITH" && last === "DATA") words(["CATEGORY"]);
  else if ((clause === "FROM" && name) || (["LIMIT", "OFFSET"].includes(clause) && /^\d+$/.test(last))) clauses();
  result.needs = [...needs];
  const rank = s => s.label.toUpperCase().replace(/\(\)$|:1$/, "") === prefix ? 0 : 1;
  items.sort((a,b) => rank(a) - rank(b) || a.label.localeCompare(b.label, "en") || a.kind.localeCompare(b.kind));
  return result;
}

function replacement(text, result, item) {
  let value = item.insert, start = result.start, end = result.end;
  let offset = value.length, selection = 0;
  const suffix = text.slice(end);
  if (item.kind === "Function") {
    if (/^\s*\(/.test(suffix)) value = value.slice(0, -2);
    offset = value.endsWith("()") ? value.length - 1 : value.length;
  } else if (item.kind === "Date" && value.endsWith(":1")) {
    if (suffix.startsWith(":")) value = value.slice(0, -2);
    else selection = 1;
    offset = value.length;
  } else if (item.kind === "Relationship" && suffix.startsWith(".")) {
    value = value.slice(0, -1); offset = value.length;
  } else if (item.kind === "Keyword" && value.includes(" ")) {
    const [head, tail] = value.split(" ");
    if (suffix.trimStart().toUpperCase().match(/^\w+/)?.[0] === tail) value = head;
    offset = value.length;
  }
  value = result.space + value;
  offset += result.space.length;
  return {text: value, start, end, anchor: start + offset - selection, focus: start + offset};
}
