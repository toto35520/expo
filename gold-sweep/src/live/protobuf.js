/**
 * Codec Protocol Buffers minimal (wire format), sans dependance.
 *
 * cTrader Open API transporte des messages protobuf sur TLS. Plutot que de
 * tirer une bibliotheque complete, on implemente exactement les types de fil
 * utilises par l'API : varint, length-delimited, fixed32/64.
 *
 * Regle d'or respectee : tout champ INCONNU est ignore proprement selon son
 * type de fil. C'est ce qui permet a ce client de survivre aux ajouts de
 * champs cote broker sans casser.
 */

const WIRE_VARINT = 0;
const WIRE_64 = 1;
const WIRE_BYTES = 2;
const WIRE_32 = 5;

/** Types scalaires supportes et leur type de fil. */
const WIRE_OF = {
  int32: WIRE_VARINT,
  int64: WIRE_VARINT,
  uint32: WIRE_VARINT,
  uint64: WIRE_VARINT,
  sint32: WIRE_VARINT,
  sint64: WIRE_VARINT,
  bool: WIRE_VARINT,
  enum: WIRE_VARINT,
  double: WIRE_64,
  fixed64: WIRE_64,
  float: WIRE_32,
  fixed32: WIRE_32,
  string: WIRE_BYTES,
  bytes: WIRE_BYTES,
  message: WIRE_BYTES,
};

// ───────────────────────────── ECRITURE ─────────────────────────────

class Writer {
  constructor() {
    this.chunks = [];
    this.len = 0;
  }

  _push(buf) {
    this.chunks.push(buf);
    this.len += buf.length;
  }

  varint(v) {
    if (typeof v === 'boolean') v = v ? 1 : 0;
    if (typeof v === 'bigint') return this.varintBig(v);
    if (!Number.isFinite(v)) throw new Error(`varint : valeur non finie (${v})`);
    if (v < 0) return this.varintBig(BigInt(Math.trunc(v)));
    if (v > Number.MAX_SAFE_INTEGER) return this.varintBig(BigInt(v));
    const out = [];
    let n = Math.trunc(v);
    do {
      let b = n % 128;
      n = Math.floor(n / 128);
      if (n > 0) b |= 0x80;
      out.push(b);
    } while (n > 0);
    this._push(Buffer.from(out));
    return this;
  }

  varintBig(v) {
    let n = BigInt(v);
    // Complement a deux sur 64 bits pour les negatifs.
    if (n < 0n) n += 1n << 64n;
    const out = [];
    do {
      let b = Number(n & 0x7fn);
      n >>= 7n;
      if (n > 0n) b |= 0x80;
      out.push(b);
    } while (n > 0n);
    this._push(Buffer.from(out));
    return this;
  }

  tag(field, wire) {
    return this.varint(field * 8 + wire);
  }

  bytes(buf) {
    this.varint(buf.length);
    this._push(buf);
    return this;
  }

  finish() {
    return Buffer.concat(this.chunks, this.len);
  }
}

/**
 * @typedef {Object<number, {name:string, type:string, repeated?:boolean, message?:object}>} Schema
 */

/**
 * Encode un objet selon un schema.
 * @param {Schema} schema
 * @param {object} obj
 * @returns {Buffer}
 */
export function encode(schema, obj) {
  const w = new Writer();
  for (const [fieldStr, def] of Object.entries(schema)) {
    const field = Number(fieldStr);
    const value = obj[def.name];
    if (value === undefined || value === null) continue;
    const wire = WIRE_OF[def.type];
    if (wire === undefined) throw new Error(`Type inconnu : ${def.type}`);

    const values = def.repeated ? value : [value];
    if (def.repeated && !Array.isArray(value)) {
      throw new Error(`Champ repete "${def.name}" : tableau attendu`);
    }

    for (const v of values) {
      if (v === undefined || v === null) continue;
      w.tag(field, wire);
      switch (def.type) {
        case 'string':
          w.bytes(Buffer.from(String(v), 'utf8'));
          break;
        case 'bytes':
          w.bytes(Buffer.isBuffer(v) ? v : Buffer.from(v));
          break;
        case 'message':
          w.bytes(encode(def.message, v));
          break;
        case 'double': {
          const b = Buffer.allocUnsafe(8);
          b.writeDoubleLE(Number(v), 0);
          w._push(b);
          break;
        }
        case 'float': {
          const b = Buffer.allocUnsafe(4);
          b.writeFloatLE(Number(v), 0);
          w._push(b);
          break;
        }
        case 'fixed64': {
          const b = Buffer.allocUnsafe(8);
          b.writeBigUInt64LE(BigInt(v), 0);
          w._push(b);
          break;
        }
        case 'fixed32': {
          const b = Buffer.allocUnsafe(4);
          b.writeUInt32LE(Number(v), 0);
          w._push(b);
          break;
        }
        case 'sint32':
        case 'sint64': {
          // ZigZag
          const n = BigInt(v);
          w.varintBig(n < 0n ? -2n * n - 1n : 2n * n);
          break;
        }
        default:
          w.varint(v);
      }
    }
  }
  return w.finish();
}

// ───────────────────────────── LECTURE ──────────────────────────────

class Reader {
  /** @param {Buffer} buf */
  constructor(buf) {
    this.buf = buf;
    this.pos = 0;
  }

  get eof() {
    return this.pos >= this.buf.length;
  }

  /** Varint en BigInt (toujours exact). */
  varintBig() {
    let result = 0n;
    let shift = 0n;
    for (let i = 0; i < 10; i++) {
      if (this.pos >= this.buf.length) throw new Error('varint tronque');
      const b = this.buf[this.pos++];
      result |= BigInt(b & 0x7f) << shift;
      if ((b & 0x80) === 0) return result;
      shift += 7n;
    }
    throw new Error('varint trop long (>10 octets)');
  }

  /** Varint en Number ; leve si la precision serait perdue. */
  varint() {
    const b = this.varintBig();
    if (b > BigInt(Number.MAX_SAFE_INTEGER)) {
      throw new Error(`varint hors precision Number : ${b}`);
    }
    return Number(b);
  }

  bytes() {
    const len = this.varint();
    if (this.pos + len > this.buf.length) throw new Error('bloc length-delimited tronque');
    const out = this.buf.subarray(this.pos, this.pos + len);
    this.pos += len;
    return out;
  }

  /** Saute un champ dont le numero est inconnu du schema. */
  skip(wire) {
    switch (wire) {
      case WIRE_VARINT:
        this.varintBig();
        break;
      case WIRE_64:
        this.pos += 8;
        break;
      case WIRE_BYTES:
        this.bytes();
        break;
      case WIRE_32:
        this.pos += 4;
        break;
      default:
        throw new Error(`Type de fil inconnu : ${wire}`);
    }
    if (this.pos > this.buf.length) throw new Error('message tronque');
  }
}

/**
 * Decode un buffer SANS schema : renvoie la liste brute des champs presents
 * avec leur numero et leur type de fil.
 *
 * C'est l'outil de decouverte : les numeros de champ de certains messages
 * cTrader (ProtoOASymbol notamment) ne sont pas garantis identiques d'un
 * broker/version a l'autre. Plutot que de deviner une disposition binaire
 * dans du code qui deplace de l'argent, on inspecte ce que le serveur envoie
 * reellement.
 *
 * @param {Buffer} buf
 * @param {number} [depth] profondeur d'exploration des sous-messages
 * @returns {Array<{field:number, wire:number, value:any, asMessage?:any}>}
 */
export function decodeUnknown(buf, depth = 1) {
  const r = new Reader(buf);
  const out = [];
  while (!r.eof) {
    const key = r.varint();
    const field = key >>> 3;
    const wire = key & 7;
    const entry = { field, wire };
    try {
      switch (wire) {
        case WIRE_VARINT: {
          const n = r.varintBig();
          entry.value = n > BigInt(Number.MAX_SAFE_INTEGER) ? n.toString() : Number(n);
          entry.hint = 'varint (int/uint/bool/enum)';
          break;
        }
        case WIRE_64: {
          entry.value = r.buf.readDoubleLE(r.pos);
          entry.raw = r.buf.readBigUInt64LE(r.pos).toString();
          r.pos += 8;
          entry.hint = 'fixed64 (double/fixed64)';
          break;
        }
        case WIRE_BYTES: {
          const b = r.bytes();
          const asText = b.toString('utf8');
          const printable = /^[\x20-\x7e\u00a0-\uffff]*$/.test(asText);
          entry.value = printable ? asText : '0x' + b.toString('hex').slice(0, 64);
          entry.hint = printable ? 'string ou message' : 'bytes ou message';
          if (depth > 0 && b.length) {
            try {
              entry.asMessage = decodeUnknown(b, depth - 1);
            } catch {
              /* pas un sous-message valide */
            }
          }
          break;
        }
        case WIRE_32: {
          entry.value = r.buf.readUInt32LE(r.pos);
          r.pos += 4;
          entry.hint = 'fixed32 (float/fixed32)';
          break;
        }
        default:
          throw new Error(`type de fil ${wire}`);
      }
    } catch (e) {
      entry.error = String(e.message || e);
      out.push(entry);
      break;
    }
    out.push(entry);
  }
  return out;
}

/**
 * Decode un buffer selon un schema. Les champs absents ne sont pas ajoutes ;
 * les champs repetes sont toujours des tableaux (vides si absents).
 *
 * @param {Schema} schema
 * @param {Buffer} buf
 * @returns {object}
 */
export function decode(schema, buf) {
  const r = new Reader(buf);
  const out = {};
  for (const def of Object.values(schema)) {
    if (def.repeated) out[def.name] = [];
  }

  while (!r.eof) {
    const key = r.varint();
    const field = key >>> 3;
    const wire = key & 7;
    const def = schema[field];
    if (!def) {
      r.skip(wire);
      continue;
    }

    // GARDE-FOU CRITIQUE : si le type de fil reel ne correspond pas a celui
    // attendu par le schema, le numero de champ a change cote serveur (ou
    // notre schema est faux). On IGNORE le champ au lieu de le mal lire :
    // une mauvaise lecture decalerait tout le reste du message, ce qui est
    // inacceptable pour du code qui place des ordres.
    if (wire !== WIRE_OF[def.type]) {
      out.__wireMismatch = out.__wireMismatch || [];
      out.__wireMismatch.push({ field, name: def.name, expected: WIRE_OF[def.type], got: wire });
      r.skip(wire);
      continue;
    }

    let value;
    switch (def.type) {
      case 'string':
        value = r.bytes().toString('utf8');
        break;
      case 'bytes':
        value = Buffer.from(r.bytes());
        break;
      case 'message':
        value = decode(def.message, r.bytes());
        break;
      case 'bool':
        value = r.varintBig() !== 0n;
        break;
      case 'double':
        value = r.buf.readDoubleLE(r.pos);
        r.pos += 8;
        break;
      case 'float':
        value = r.buf.readFloatLE(r.pos);
        r.pos += 4;
        break;
      case 'fixed64':
        value = r.buf.readBigUInt64LE(r.pos);
        r.pos += 8;
        value = value > BigInt(Number.MAX_SAFE_INTEGER) ? value : Number(value);
        break;
      case 'fixed32':
        value = r.buf.readUInt32LE(r.pos);
        r.pos += 4;
        break;
      case 'sint32':
      case 'sint64': {
        const z = r.varintBig();
        const n = (z >> 1n) ^ -(z & 1n);
        value = n > BigInt(Number.MAX_SAFE_INTEGER) || n < BigInt(Number.MIN_SAFE_INTEGER) ? n : Number(n);
        break;
      }
      case 'int32':
      case 'int64': {
        // int64 negatif = complement a deux sur 64 bits.
        let n = r.varintBig();
        if (n >= 1n << 63n) n -= 1n << 64n;
        value = n > BigInt(Number.MAX_SAFE_INTEGER) || n < BigInt(Number.MIN_SAFE_INTEGER) ? n : Number(n);
        break;
      }
      default: {
        const n = r.varintBig();
        value = n > BigInt(Number.MAX_SAFE_INTEGER) ? n : Number(n);
      }
    }

    if (def.repeated) out[def.name].push(value);
    else out[def.name] = value;
  }
  return out;
}
