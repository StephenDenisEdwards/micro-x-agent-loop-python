# Authentication System

A full-stack authentication system built with .NET 8 Web API and React.

## Features

### Backend (.NET 8 Web API)
- User registration and login
- JWT token-based authentication
- Refresh token mechanism
- Password hashing with BCrypt
- SQLite database with Entity Framework Core
- RESTful API endpoints
- Swagger documentation
- CORS configuration

### Frontend (React)
- User registration form
- Login form
- Protected routes
- Automatic token refresh
- User dashboard
- User list display
- Modern UI with gradient design

## Project Structure

```
AuthSystem/
├── AuthSystem.Api/              # .NET Backend
│   ├── Controllers/             # API Controllers
│   ├── Data/                    # Database context and entities
│   ├── Models/                  # DTOs and request/response models
│   ├── Services/                # Business logic
│   ├── Program.cs               # Application entry point
│   └── appsettings.json         # Configuration
│
├── auth-frontend/               # React Frontend
│   ├── public/                  # Static files
│   ├── src/
│   │   ├── components/          # React components
│   │   ├── context/             # Auth context provider
│   │   ├── App.js               # Main app component
│   │   └── index.js             # Entry point
│   └── package.json
│
├── setup-backend.bat            # Backend setup script
├── start-backend.bat            # Start backend server
├── setup-frontend.bat           # Frontend setup script
└── start-frontend.bat           # Start frontend dev server
```

## Prerequisites

- .NET 8 SDK
- Node.js (v16 or higher)
- npm

## Installation & Setup

### 1. Backend Setup

```bash
# Run the setup script
setup-backend.bat

# Or manually:
cd AuthSystem.Api
dotnet restore
dotnet build
```

### 2. Frontend Setup

```bash
# Run the setup script
setup-frontend.bat

# Or manually:
cd auth-frontend
npm install
```

## Running the Application

### Start Backend (Terminal 1)
```bash
start-backend.bat
# Or: cd AuthSystem.Api && dotnet run
```
The API will run on https://localhost:5001

### Start Frontend (Terminal 2)
```bash
start-frontend.bat
# Or: cd auth-frontend && npm start
```
The React app will run on http://localhost:3000

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login user
- `POST /api/auth/refresh` - Refresh access token
- `GET /api/auth/me` - Get current user (protected)

### Users
- `GET /api/users` - Get all users (protected)
- `GET /api/users/{id}` - Get user by ID (protected)

## API Documentation

Once the backend is running, visit https://localhost:5001/swagger to view the interactive API documentation.

## Security Features

- Passwords hashed with BCrypt
- JWT access tokens (15-minute expiry)
- Refresh tokens (7-day expiry)
- Automatic token refresh on expiry
- Protected API endpoints
- CORS configuration

## Database

The application uses SQLite for data storage. The database file (`authsystem.db`) is created automatically in the `AuthSystem.Api` directory.

### User Schema
- Id (int, primary key)
- Email (string, unique)
- PasswordHash (string)
- FirstName (string)
- LastName (string)
- RefreshToken (string, nullable)
- RefreshTokenExpiryTime (DateTime, nullable)
- CreatedAt (DateTime)
- LastLoginAt (DateTime, nullable)

## Configuration

### Backend (appsettings.json)
- Connection string
- JWT settings (secret key, issuer, audience)
- Logging configuration

### Frontend
- API URL: https://localhost:5001/api
- Token storage: localStorage

## Testing

### Test User Registration
1. Navigate to http://localhost:3000/register
2. Fill in the registration form
3. Submit to create a new user

### Test Login
1. Navigate to http://localhost:3000/login
2. Enter registered credentials
3. Access protected dashboard

## Troubleshooting

### Backend Issues
- Ensure .NET 8 SDK is installed: `dotnet --version`
- Check if port 5001 is available
- Delete `authsystem.db` and restart to reset database

### Frontend Issues
- Ensure Node.js is installed: `node --version`
- Clear npm cache: `npm cache clean --force`
- Delete `node_modules` and run `npm install` again
- Check if port 3000 is available

### CORS Issues
- Ensure backend CORS policy includes http://localhost:3000
- Check browser console for CORS errors

## Future Enhancements

- Email verification
- Password reset functionality
- Role-based authorization
- User profile editing
- Profile picture upload
- Two-factor authentication
- Remember me functionality
- Social login (Google, Facebook)

## License

MIT License
