package com.tm.kintaramarket;

import java.math.BigInteger;
import java.util.Arrays;

/** Minimal Bitcoin/Solana-style Base58 codec. */
public final class Base58 {
    private static final char[] ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz".toCharArray();
    private static final int[] INDEXES = new int[128];
    static {
        Arrays.fill(INDEXES, -1);
        for (int i = 0; i < ALPHABET.length; i++) INDEXES[ALPHABET[i]] = i;
    }
    private Base58() {}

    public static String encode(byte[] input) {
        if (input == null || input.length == 0) return "";
        int zeros = 0;
        while (zeros < input.length && input[zeros] == 0) zeros++;
        byte[] copy = Arrays.copyOf(input, input.length);
        char[] encoded = new char[input.length * 2];
        int out = encoded.length;
        int start = zeros;
        while (start < copy.length) {
            int mod = divmod58(copy, start);
            if (copy[start] == 0) start++;
            encoded[--out] = ALPHABET[mod];
        }
        while (out < encoded.length && encoded[out] == ALPHABET[0]) out++;
        while (zeros-- > 0) encoded[--out] = ALPHABET[0];
        return new String(encoded, out, encoded.length - out);
    }

    public static byte[] decode(String input) {
        if (input == null || input.isEmpty()) return new byte[0];
        byte[] input58 = new byte[input.length()];
        for (int i = 0; i < input.length(); i++) {
            char c = input.charAt(i);
            int digit = c < 128 ? INDEXES[c] : -1;
            if (digit < 0) throw new IllegalArgumentException("Invalid Base58 character");
            input58[i] = (byte) digit;
        }
        int zeros = 0;
        while (zeros < input58.length && input58[zeros] == 0) zeros++;
        byte[] decoded = new byte[input.length()];
        int out = decoded.length;
        int start = zeros;
        while (start < input58.length) {
            int mod = divmod256(input58, start);
            if (input58[start] == 0) start++;
            decoded[--out] = (byte) mod;
        }
        while (out < decoded.length && decoded[out] == 0) out++;
        return Arrays.copyOfRange(decoded, out - zeros, decoded.length);
    }

    private static int divmod58(byte[] number, int startAt) {
        int remainder = 0;
        for (int i = startAt; i < number.length; i++) {
            int digit256 = number[i] & 0xFF;
            int temp = remainder * 256 + digit256;
            number[i] = (byte) (temp / 58);
            remainder = temp % 58;
        }
        return remainder;
    }

    private static int divmod256(byte[] number58, int startAt) {
        int remainder = 0;
        for (int i = startAt; i < number58.length; i++) {
            int digit58 = number58[i] & 0xFF;
            int temp = remainder * 58 + digit58;
            number58[i] = (byte) (temp / 256);
            remainder = temp % 256;
        }
        return remainder;
    }
}
