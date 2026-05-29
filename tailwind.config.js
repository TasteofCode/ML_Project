/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        xp: {
          blue: '#245DDA',
          lightBlue: '#316AC5',
          grayDark: '#7A7A7A',
          grayLight: '#D4D0C8',
          grayFace: '#ECE9D8',
          windowFrame: '#002E94',
        }
      },
      fontFamily: {
        tahoma: ['Tahoma', 'MS Sans Serif', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
