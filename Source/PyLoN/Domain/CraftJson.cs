using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace PyLoN
{
    /// <summary>Bounded JSON for craft-builder messages, independent of Unity and DTO reflection.</summary>
    public static class CraftJson
    {
        private const int MaxBytes = 1024 * 1024, MaxDepth = 32, MaxNodes = 32768;
        private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);

        // Limits count containers and scalar values, including object keys, as nodes.
        // Depth counts nested containers: 32 containers enclosing a scalar are allowed.
        // Numbers are int when an integer token fits Int32, otherwise finite double.
        public static object Parse(string json)
        {
            CheckText(json);
            var reader = new Reader(json);
            object value = reader.Value(0);
            reader.Space();
            if (reader.Offset != json.Length) throw new FormatException("Trailing JSON characters.");
            return value;
        }

        public static string Stringify(object value)
        {
            var writer = new Writer();
            writer.Value(value, 0);
            string json = writer.Text.ToString();
            CheckText(json);
            return json;
        }

        private static void CheckText(string text)
        {
            if (text == null) throw new ArgumentNullException("text");
            if (text.Length > MaxBytes) throw new FormatException("JSON exceeds 1 MiB.");
            try
            {
                if (Utf8.GetByteCount(text) > MaxBytes)
                    throw new FormatException("JSON exceeds 1 MiB in UTF-8.");
            }
            catch (EncoderFallbackException ex) { throw new FormatException("Invalid Unicode surrogate.", ex); }
        }

        private static bool Digit(char c) { return c >= '0' && c <= '9'; }
        private static bool Finite(double n) { return !double.IsNaN(n) && !double.IsInfinity(n); }

        private sealed class Reader
        {
            private readonly string text;
            private int nodes;
            internal int Offset;
            internal Reader(string text) { this.text = text; }
            private char Peek { get { return Offset < text.Length ? text[Offset] : '\0'; } }
            private FormatException Error() { return new FormatException("Invalid JSON at offset " + Offset + "."); }
            private void Node() { if (++nodes > MaxNodes) throw new FormatException("JSON node limit exceeded."); }
            internal void Space()
            {
                while (Peek == ' ' || Peek == '\t' || Peek == '\r' || Peek == '\n') Offset++;
            }
            private bool Take(char c)
            {
                if (Offset >= text.Length || Peek != c) return false;
                Offset++;
                return true;
            }
            private void Expect(char c) { if (!Take(c)) throw Error(); }

            internal object Value(int depth)
            {
                Node();
                Space();
                char c = Peek;
                if (c == '"') return String();
                if (c == '{' || c == '[')
                {
                    if (depth >= MaxDepth) throw new FormatException("JSON depth limit exceeded.");
                    Offset++;
                    Space();
                    if (c == '[')
                    {
                        var list = new List<object>();
                        if (Take(']')) return list;
                        do { list.Add(Value(depth + 1)); Space(); } while (Take(','));
                        Expect(']');
                        return list;
                    }
                    var map = new Dictionary<string, object>(StringComparer.Ordinal);
                    if (Take('}')) return map;
                    do
                    {
                        Space();
                        Node();
                        string key = String();
                        if (map.ContainsKey(key)) throw new FormatException("Duplicate JSON key: " + key);
                        Space();
                        Expect(':');
                        map.Add(key, Value(depth + 1));
                        Space();
                    } while (Take(','));
                    Expect('}');
                    return map;
                }
                if (c == 't') { Literal("true"); return true; }
                if (c == 'f') { Literal("false"); return false; }
                if (c == 'n') { Literal("null"); return null; }
                if (c == '-' || Digit(c)) return Number();
                throw Error();
            }

            private void Literal(string value)
            {
                for (int i = 0; i < value.Length; i++) Expect(value[i]);
            }

            private string String()
            {
                Expect('"');
                var result = new StringBuilder();
                while (Offset < text.Length)
                {
                    char c = text[Offset++];
                    if (c == '"')
                    {
                        string value = result.ToString();
                        CheckText(value); // Reject unpaired escaped surrogates as well as raw ones.
                        return value;
                    }
                    if (c < 0x20) throw Error();
                    if (c == '\\')
                    {
                        if (Offset == text.Length) throw Error();
                        c = text[Offset++];
                        switch (c)
                        {
                            case '"': case '\\': case '/': break;
                            case 'b': c = '\b'; break;
                            case 'f': c = '\f'; break;
                            case 'n': c = '\n'; break;
                            case 'r': c = '\r'; break;
                            case 't': c = '\t'; break;
                            case 'u':
                                int code = 0;
                                for (int i = 0; i < 4; i++)
                                {
                                    if (Offset == text.Length) throw Error();
                                    char h = text[Offset++];
                                    int hex = h >= '0' && h <= '9' ? h - '0'
                                        : h >= 'a' && h <= 'f' ? h - 'a' + 10
                                        : h >= 'A' && h <= 'F' ? h - 'A' + 10 : -1;
                                    if (hex < 0) throw Error();
                                    code = code * 16 + hex;
                                }
                                c = (char)code;
                                break;
                            default: throw Error();
                        }
                    }
                    result.Append(c);
                }
                throw Error();
            }

            private object Number()
            {
                int start = Offset;
                Take('-');
                if (!Take('0'))
                {
                    if (!Digit(Peek)) throw Error();
                    while (Digit(Peek)) Offset++;
                }
                if (Take('.'))
                {
                    if (!Digit(Peek)) throw Error();
                    while (Digit(Peek)) Offset++;
                }
                if (Take('e') || Take('E'))
                {
                    if (!Take('+')) Take('-');
                    if (!Digit(Peek)) throw Error();
                    while (Digit(Peek)) Offset++;
                }
                string token = text.Substring(start, Offset - start);
                int integer;
                if (int.TryParse(token, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture,
                                 out integer)) return integer;
                double number;
                if (!double.TryParse(token, NumberStyles.Float, CultureInfo.InvariantCulture,
                                     out number) || !Finite(number)) throw Error();
                return number;
            }
        }

        private sealed class Writer
        {
            internal readonly StringBuilder Text = new StringBuilder();
            private int nodes;
            private void Node() { if (++nodes > MaxNodes) throw new FormatException("JSON node limit exceeded."); }
            private void Append(string value)
            {
                if (value.Length > MaxBytes - Text.Length) throw new FormatException("JSON exceeds 1 MiB.");
                Text.Append(value);
            }
            private void String(string value)
            {
                CheckText(value);
                Append("\"");
                foreach (char c in value)
                {
                    if (c == '"') Append("\\\"");
                    else if (c == '\\') Append("\\\\");
                    else if (c < 0x20) Append("\\u" + ((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    else Append(c.ToString());
                }
                Append("\"");
            }
            internal void Value(object value, int depth)
            {
                Node();
                if (value == null) { Append("null"); return; }
                if (value is string) { String((string)value); return; }
                if (value is bool) { Append((bool)value ? "true" : "false"); return; }
                if (value is int) { Append(((int)value).ToString(CultureInfo.InvariantCulture)); return; }
                if (value is uint) { Append(((uint)value).ToString(CultureInfo.InvariantCulture)); return; }
                if (value is double)
                {
                    double number = (double)value;
                    if (!Finite(number)) throw new FormatException("Nonfinite JSON number.");
                    Append(number.ToString("R", CultureInfo.InvariantCulture));
                    return;
                }
                if (depth >= MaxDepth) throw new FormatException("JSON depth limit exceeded.");
                var map = value as Dictionary<string, object>;
                var list = value as IEnumerable;
                bool first = true;
                if (map != null)
                {
                    Append("{");
                    foreach (var pair in map)
                    {
                        if (!first) Append(",");
                        first = false;
                        Node(); String(pair.Key); Append(":"); Value(pair.Value, depth + 1);
                    }
                    Append("}");
                }
                else if (list != null)
                {
                    Append("[");
                    foreach (object item in list)
                    {
                        if (!first) Append(",");
                        first = false;
                        Value(item, depth + 1);
                    }
                    Append("]");
                }
                else throw new FormatException("Unsupported JSON value type: " + value.GetType().FullName);
            }
        }
    }
}
